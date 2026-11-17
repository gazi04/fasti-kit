import uuid
from datetime import UTC, datetime, timedelta

from saq import Worker
from sqlalchemy import select

from core.dead_letter.hook import record_dead_letter
from core.dead_letter.model import DeadLetterJobModel
from core.dead_letter.settings import get_dead_letter_settings
from core.dead_letter.tasks import cleanup_dead_letter_task
from core.outbox.model import OutboxEvent
from core.outbox.settings import get_outbox_settings
from core.outbox.tasks import cleanup_outbox_task
from core.worker.main import settings


def _days_ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


async def test_cleanup_outbox_task_deletes_only_dispatched_rows_past_retention(
    db,
) -> None:
    past_retention = _days_ago(get_outbox_settings().retention_days + 1)
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
    past_retention = _days_ago(get_dead_letter_settings().retention_days + 1)

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


async def test_worker_settings_register_the_outbox_jobs_and_hooks() -> None:
    worker = Worker(**settings)

    assert {"cleanup_outbox_task", "cleanup_dead_letter_task"} <= set(worker.functions)
    assert settings["after_process"] is record_dead_letter
    assert "startup" in settings
