from collections.abc import Callable
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import after_commit
from core.outbox.repository import OutboxRepository
from core.queue import enqueue_task


class TaskStager(Protocol):
    async def stage_add(self, task_name: str, payload: dict[str, Any]) -> object: ...


class EnqueueAfterCommit:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def stage_add(self, task_name: str, payload: dict[str, Any]) -> None:
        async def _enqueue() -> None:
            await enqueue_task(task_name, key=f"{task_name}:{uuid4()}", **payload)

        after_commit(self.db, _enqueue)


_factory: Callable[[AsyncSession], TaskStager] = OutboxRepository


def task_stager(db: AsyncSession) -> TaskStager:
    return _factory(db)
