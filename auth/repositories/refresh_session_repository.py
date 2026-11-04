from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth.entities.refresh_session import RefreshSession
from auth.models.refresh_session_model import RefreshSessionModel
from core.database import force_primary_var, transaction


class RefreshSessionRepository:
    def __init__(self, db) -> None:
        self.db: AsyncSession = db

    async def create(self, user_id: UUID, expires_at: datetime) -> RefreshSession:
        force_primary_var.set(True)
        model = RefreshSessionModel(user_id=user_id, expires_at=expires_at)

        async with transaction(self.db):
            self.db.add(model)
            await self.db.flush()
            return self._to_entity(model)

    async def rotate(
        self, session_id: UUID, user_id: UUID, generation: int
    ) -> RefreshSession | None:
        force_primary_var.set(True)
        now = datetime.now(UTC)
        claim = (
            update(RefreshSessionModel)
            .where(
                RefreshSessionModel.id == session_id,
                RefreshSessionModel.user_id == user_id,
                RefreshSessionModel.generation == generation,
                RefreshSessionModel.revoked_at.is_(None),
                RefreshSessionModel.expires_at > now,
            )
            .values(generation=RefreshSessionModel.generation + 1, rotated_at=now)
            .returning(RefreshSessionModel)
        )

        async with transaction(self.db):
            model = (await self.db.scalars(claim)).one_or_none()
            return None if model is None else self._to_entity(model)

    async def get(self, session_id: UUID) -> RefreshSession | None:
        token = force_primary_var.set(True)
        try:
            model = await self.db.get(
                RefreshSessionModel, session_id, populate_existing=True
            )
        finally:
            force_primary_var.reset(token)

        return None if model is None else self._to_entity(model)

    async def revoke(self, session_id: UUID) -> None:
        async with transaction(self.db):
            await self._revoke_where(RefreshSessionModel.id == session_id)

    async def stage_revoke(self, session_id: UUID, user_id: UUID) -> None:
        await self._revoke_where(
            RefreshSessionModel.id == session_id,
            RefreshSessionModel.user_id == user_id,
        )

    async def stage_revoke_all_for_user(self, user_id: UUID) -> None:
        await self._revoke_where(RefreshSessionModel.user_id == user_id)

    async def purge_expired(self) -> int:
        force_primary_var.set(True)
        async with transaction(self.db):
            result = await self.db.execute(
                delete(RefreshSessionModel)
                .where(RefreshSessionModel.expires_at <= datetime.now(UTC))
                .returning(RefreshSessionModel.id)
            )
            return len(result.scalars().all())

    async def _revoke_where(self, *conditions) -> None:
        force_primary_var.set(True)
        await self.db.execute(
            update(RefreshSessionModel)
            .where(*conditions, RefreshSessionModel.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )

    @staticmethod
    def _to_entity(model: RefreshSessionModel) -> RefreshSession:
        return RefreshSession(
            id=model.id,
            user_id=model.user_id,
            generation=model.generation,
            expires_at=model.expires_at,
            rotated_at=model.rotated_at,
            revoked_at=model.revoked_at,
        )
