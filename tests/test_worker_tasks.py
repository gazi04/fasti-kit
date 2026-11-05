import uuid
from datetime import UTC, datetime, timedelta

from saq import Worker
from sqlalchemy import select

from auth.models.refresh_session_model import RefreshSessionModel
from auth.models.revoked_token_model import RevokedTokenModel
from core.dead_letter.hook import record_dead_letter
from core.dead_letter.model import DeadLetterJobModel
from core.factories.user_factory import make_email
from core.outbox.model import OutboxEvent
from core.setting import get_settings
from core.worker.main import settings
from core.worker.tasks import (
    cleanup_dead_letter_task,
    cleanup_outbox_task,
    cleanup_refresh_sessions_task,
    cleanup_revoked_tokens_task,
)
from user.repositories.user_repository import UserRepository

app_settings = get_settings()


def _days_ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


async def test_cleanup_revoked_tokens_task_deletes_only_expired_rows(db) -> None:
    expired_jti = f"expired-{uuid.uuid4().hex[:8]}"
    live_jti = f"live-{uuid.uuid4().hex[:8]}"
    db.add(RevokedTokenModel(jti=expired_jti, expires_at=_days_ago(1 / 24)))
    db.add(RevokedTokenModel(jti=live_jti, expires_at=_days_ago(-1 / 24)))
    await db.flush()

    await cleanup_revoked_tokens_task(ctx={})

    remaining = (await db.scalars(select(RevokedTokenModel.jti))).all()
    assert expired_jti not in remaining
    assert live_jti in remaining


async def test_cleanup_refresh_sessions_task_deletes_only_expired_rows(db) -> None:
    user = await UserRepository(db).add("Sessions", make_email(), "pw")
    expired = RefreshSessionModel(user_id=user.id, expires_at=_days_ago(1 / 24))
    live = RefreshSessionModel(user_id=user.id, expires_at=_days_ago(-1))
    db.add_all([expired, live])
    await db.flush()

    result = await cleanup_refresh_sessions_task(ctx={})

    remaining = set((await db.scalars(select(RefreshSessionModel.id))).all())
    assert result == {"status": "completed", "deleted": 1}
    assert expired.id not in remaining
    assert live.id in remaining


async def test_cleanup_outbox_task_deletes_only_dispatched_rows_past_retention(
    db,
) -> None:
    past_retention = _days_ago(app_settings.outbox_retention_days + 1)
    old_dispatched = OutboxEvent(
        task_name="send_email_task", payload={}, dispatched_at=past_retention
    )
    recent_dispatched = OutboxEvent(
        task_name="send_email_task", payload={}, dispatched_at=_days_ago(0)
    )
    old_pending = OutboxEvent(
        task_name="send_email_task", payload={}, created_at=past_retention
    )
    db.add_all([old_dispatched, recent_dispatched, old_pending])
    await db.flush()

    result = await cleanup_outbox_task(ctx={})

    remaining = set((await db.scalars(select(OutboxEvent.id))).all())
    assert result == {"status": "completed", "deleted": 1}
    assert old_dispatched.id not in remaining
    assert {recent_dispatched.id, old_pending.id} <= remaining


async def test_cleanup_dead_letter_task_deletes_only_retried_rows_past_retention(
    db,
) -> None:
    past_retention = _days_ago(app_settings.dead_letter_retention_days + 1)

    def _job(*, retried_at: datetime | None) -> DeadLetterJobModel:
        return DeadLetterJobModel(
            job_key=f"job-{uuid.uuid4().hex[:8]}",
            function="send_email_task",
            queue_name="default",
            kwargs={},
            status="failed",
            error="boom",
            attempts=3,
            failed_at=past_retention,
            retried_at=retried_at,
        )

    old_retried = _job(retried_at=past_retention)
    old_unretried = _job(retried_at=None)
    db.add_all([old_retried, old_unretried])
    await db.flush()

    result = await cleanup_dead_letter_task(ctx={})

    remaining = set((await db.scalars(select(DeadLetterJobModel.id))).all())
    assert result == {"status": "completed", "deleted": 1}
    assert old_retried.id not in remaining
    assert old_unretried.id in remaining


async def test_worker_settings_register_all_task_functions() -> None:
    """Worker(**settings) builds a valid config: every task + cron function is registered
    and every cron expression is valid (Worker.__init__ raises on a bad cron string)."""
    worker = Worker(**settings)

    assert set(worker.functions) >= {
        "process_welcome_email",
        "send_email_task",
        "cleanup_revoked_tokens_task",
        "cleanup_refresh_sessions_task",
        "cleanup_outbox_task",
        "cleanup_dead_letter_task",
    }
    assert settings["after_process"] is record_dead_letter
