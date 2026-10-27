from typing import Any

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
