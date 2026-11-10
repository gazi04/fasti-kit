import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import force_primary_var, transaction
from core.outbox.model import OutboxEvent

logger = logging.getLogger(__name__)

Send = Callable[[str, str, dict[str, Any]], Awaitable[None]]


class OutboxRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db: AsyncSession = db

    async def stage_add(self, task_name: str, payload: dict[str, Any]) -> OutboxEvent:
        force_primary_var.set(True)
        event = OutboxEvent(task_name=task_name, payload=payload)
        self.db.add(event)
        await self.db.flush()
        return event

    async def dispatch_pending(
        self, batch_size: int, *, max_attempts: int, send: Send
    ) -> tuple[int, int]:
        force_primary_var.set(True)
        dispatched = 0
        failed = 0

        async with transaction(self.db):
            result = await self.db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.dispatched_at.is_(None),
                    OutboxEvent.failed_at.is_(None),
                )
                .order_by(OutboxEvent.created_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            rows = result.scalars().all()

            for row in rows:
                try:
                    await send(row.task_name, f"outbox:{row.id}", row.payload)
                    row.dispatched_at = datetime.now(UTC)
                    dispatched += 1
                except Exception as err:
                    self._record_failure(row, err, max_attempts)
                    failed += 1

        return dispatched, failed

    async def purge_dispatched(self, before: datetime) -> int:
        force_primary_var.set(True)
        async with transaction(self.db):
            result = await self.db.execute(
                delete(OutboxEvent)
                .where(
                    OutboxEvent.dispatched_at.is_not(None),
                    OutboxEvent.dispatched_at < before,
                )
                .returning(OutboxEvent.id)
            )
            return len(result.scalars().all())

    async def oldest_pending_age(self) -> float | None:
        force_primary_var.set(True)
        oldest = await self.db.scalar(
            select(func.min(OutboxEvent.created_at)).where(
                OutboxEvent.dispatched_at.is_(None),
                OutboxEvent.failed_at.is_(None),
            )
        )
        if oldest is None:
            return None
        return (datetime.now(UTC) - oldest).total_seconds()

    @staticmethod
    def _record_failure(row: OutboxEvent, err: Exception, max_attempts: int) -> None:
        row.attempts += 1
        row.last_error = repr(err)[:1000]
        if row.attempts >= max_attempts:
            row.failed_at = datetime.now(UTC)
            logger.error(
                "Outbox row %s permanently failed after %d attempts: %s",
                row.id,
                row.attempts,
                err,
            )
