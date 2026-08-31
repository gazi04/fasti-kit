import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal, force_primary_var
from core.outbox.model import OutboxEvent
from core.queue import enqueue_task
from core.setting import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def dispatch_pending(db: AsyncSession, *, batch_size: int) -> tuple[int, int]:
    force_primary_var.set(True)

    rows = (
        (
            await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.dispatched_at.is_(None),
                    OutboxEvent.failed_at.is_(None),
                )
                .order_by(OutboxEvent.created_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )

    dispatched = 0
    failed = 0
    for row in rows:
        try:
            await enqueue_task(row.task_name, key=f"outbox:{row.id}", **row.payload)
            row.dispatched_at = datetime.now(UTC)
            dispatched += 1
        except Exception as err:
            row.attempts += 1
            row.last_error = repr(err)[:1000]
            if row.attempts >= settings.outbox_max_attempts:
                row.failed_at = datetime.now(UTC)
                logger.error(
                    "Outbox row %s permanently failed after %d attempts: %s",
                    row.id,
                    row.attempts,
                    err,
                )
            failed += 1

    await db.commit()
    return dispatched, failed


async def cleanup_dispatched(db: AsyncSession) -> int:
    force_primary_var.set(True)
    cutoff = datetime.now(UTC) - timedelta(days=settings.outbox_retention_days)
    deleted = await db.execute(
        delete(OutboxEvent)
        .where(
            OutboxEvent.dispatched_at.is_not(None),
            OutboxEvent.dispatched_at < cutoff,
        )
        .returning(OutboxEvent.id)
    )
    await db.commit()
    return len(deleted.scalars().all())


async def relay_loop() -> None:
    while True:
        try:
            async with AsyncSessionLocal() as db:
                dispatched, failed = await dispatch_pending(
                    db, batch_size=settings.outbox_batch_size
                )
            if dispatched or failed:
                logger.info("Outbox relay: dispatched=%d failed=%d", dispatched, failed)
        except Exception:
            logger.exception("Outbox relay iteration failed; retrying")

        await asyncio.sleep(settings.outbox_poll_interval)
