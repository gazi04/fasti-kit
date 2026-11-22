from datetime import UTC, datetime, timedelta

from saq import Worker
from sqlalchemy import select

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


async def test_worker_settings_register_the_outbox_relay_and_cleanup() -> None:
    worker = Worker(**settings)

    assert "cleanup_outbox_task" in worker.functions
    assert "startup" in settings
