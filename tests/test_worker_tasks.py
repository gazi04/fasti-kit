import uuid
from datetime import UTC, datetime, timedelta

from saq import Worker
from sqlalchemy import delete, select

from auth.models.revoked_token_model import RevokedTokenModel
from core.database import AsyncSessionLocal
from core.worker.main import settings
from core.worker.tasks import cleanup_outbox_task, cleanup_revoked_tokens_task


async def test_cleanup_revoked_tokens_task_deletes_only_expired_rows() -> None:
    """cleanup_revoked_tokens_task removes expired revoked-token rows and leaves unexpired ones."""
    expired_jti = f"expired-{uuid.uuid4().hex[:8]}"
    live_jti = f"live-{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        db.add(
            RevokedTokenModel(
                jti=expired_jti, expires_at=datetime.now(UTC) - timedelta(hours=1)
            )
        )
        db.add(
            RevokedTokenModel(
                jti=live_jti, expires_at=datetime.now(UTC) + timedelta(hours=1)
            )
        )
        await db.commit()

    try:
        await cleanup_revoked_tokens_task(ctx={})

        async with AsyncSessionLocal() as db:
            remaining = (await db.scalars(select(RevokedTokenModel.jti))).all()

        assert expired_jti not in remaining
        assert live_jti in remaining
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(RevokedTokenModel).where(
                    RevokedTokenModel.jti.in_([expired_jti, live_jti])
                )
            )
            await db.commit()


async def test_worker_settings_register_all_task_functions() -> None:
    """Worker(**settings) builds a valid config: every task + cron function is registered
    and every cron expression is valid (Worker.__init__ raises on a bad cron string)."""
    worker = Worker(**settings)

    assert set(worker.functions) >= {
        "process_welcome_email",
        "send_email_task",
        "cleanup_revoked_tokens_task",
        "cleanup_outbox_task",
    }


async def test_cleanup_outbox_task_runs_without_error() -> None:
    result = await cleanup_outbox_task(ctx={})
    assert result["status"] == "completed"
    assert "deleted" in result
