from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi_pagination.cursor import CursorPage, CursorParams
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import force_primary_var, transaction
from core.dead_letter.entity import DeadLetterJob
from core.dead_letter.model import DeadLetterJobModel


class DeadLetterJobRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db: AsyncSession = db

    async def record(
        self,
        *,
        job_key: str,
        function: str,
        queue_name: str,
        kwargs: dict[str, Any],
        status: str,
        error: str | None,
        attempts: int,
    ) -> DeadLetterJob:
        force_primary_var.set(True)
        model = DeadLetterJobModel(
            job_key=job_key,
            function=function,
            queue_name=queue_name,
            kwargs=kwargs,
            status=status,
            error=error,
            attempts=attempts,
        )
        async with transaction(self.db):
            self.db.add(model)
            await self.db.flush()
            await self.db.refresh(model)
            return self._to_entity(model)

    async def list(
        self, params: CursorParams | None = None, *, unresolved_only: bool = False
    ) -> CursorPage[DeadLetterJob]:
        stmt = select(DeadLetterJobModel).order_by(
            DeadLetterJobModel.failed_at.desc(), DeadLetterJobModel.id.desc()
        )
        if unresolved_only:
            stmt = stmt.where(DeadLetterJobModel.retried_at.is_(None))

        return await apaginate(
            self.db,
            stmt,
            params=params or CursorParams(),
            transformer=lambda models: [self._to_entity(model) for model in models],
        )

    async def get(self, job_id: UUID) -> DeadLetterJob | None:
        model = await self.db.get(DeadLetterJobModel, job_id)

        if model is None:
            return None

        return self._to_entity(model)

    async def mark_retried(self, job_id: UUID) -> DeadLetterJob | None:
        force_primary_var.set(True)
        model = await self.db.get(DeadLetterJobModel, job_id)

        if model is None:
            return None

        async with transaction(self.db):
            model.retried_at = datetime.now(UTC)
            await self.db.flush()
            await self.db.refresh(model)
            return self._to_entity(model)

    async def delete(self, job_id: UUID) -> bool:
        force_primary_var.set(True)
        model = await self.db.get(DeadLetterJobModel, job_id)

        if model is None:
            return False

        async with transaction(self.db):
            await self.db.delete(model)

        return True

    async def purge(
        self,
        *,
        before: datetime | None = None,
        only_retried: bool = True,
    ) -> int:
        force_primary_var.set(True)
        stmt = delete(DeadLetterJobModel).returning(DeadLetterJobModel.id)

        if before is not None:
            stmt = stmt.where(DeadLetterJobModel.failed_at < before)
        if only_retried:
            stmt = stmt.where(DeadLetterJobModel.retried_at.is_not(None))

        async with transaction(self.db):
            result = await self.db.execute(stmt)
            return len(result.scalars().all())

    @staticmethod
    def _to_entity(model: DeadLetterJobModel) -> DeadLetterJob:
        return DeadLetterJob(
            id=model.id,
            job_key=model.job_key,
            function=model.function,
            queue_name=model.queue_name,
            kwargs=model.kwargs,
            status=model.status,
            error=model.error,
            attempts=model.attempts,
            failed_at=model.failed_at,
            retried_at=model.retried_at,
        )
