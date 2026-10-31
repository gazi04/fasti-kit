from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import force_primary_var
from core.outbox.model import OutboxEvent


class OutboxRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db: AsyncSession = db

    async def stage_add(self, task_name: str, payload: dict[str, Any]) -> OutboxEvent:
        force_primary_var.set(True)
        event = OutboxEvent(task_name=task_name, payload=payload)
        self.db.add(event)
        await self.db.flush()
        return event

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
