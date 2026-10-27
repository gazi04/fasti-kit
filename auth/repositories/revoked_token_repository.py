from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth.entities.revoked_token import RevokedToken
from auth.models.revoked_token_model import RevokedTokenModel
from core.database import force_primary_var, transaction
from core.exception import ConflictError


class RevokedTokenRepository:
    def __init__(self, db) -> None:
        self.db: AsyncSession = db

    async def add(self, jti: str, expires_at: datetime) -> RevokedToken:
        async with transaction(self.db):
            return await self.stage_add(jti, expires_at)

    async def exists(self, jti: str) -> bool:
        token = force_primary_var.set(True)
        try:
            result = await self.db.scalar(
                select(RevokedTokenModel).where(
                    RevokedTokenModel.jti == jti,
                    RevokedTokenModel.expires_at > datetime.now(UTC),
                )
            )
        finally:
            force_primary_var.reset(token)

        return result is not None

    async def purge_expired(self) -> int:
        force_primary_var.set(True)
        async with transaction(self.db):
            result = await self.db.execute(
                delete(RevokedTokenModel)
                .where(RevokedTokenModel.expires_at <= datetime.now(UTC))
                .returning(RevokedTokenModel.id)
            )
            return len(result.scalars().all())

    async def stage_add(self, jti: str, expires_at: datetime) -> RevokedToken:
        force_primary_var.set(True)
        model = RevokedTokenModel(jti=jti, expires_at=expires_at)

        try:
            self.db.add(model)
            await self.db.flush()
        except IntegrityError as err:
            raise ConflictError("Token already used") from err

        return self._to_entity(model)

    async def stage_add_if_absent(self, jti: str, expires_at: datetime) -> None:
        force_primary_var.set(True)
        await self.db.execute(
            insert(RevokedTokenModel)
            .values(jti=jti, expires_at=expires_at)
            .on_conflict_do_nothing(index_elements=["jti"])
        )

    @staticmethod
    def _to_entity(model: RevokedTokenModel) -> RevokedToken:
        return RevokedToken(id=model.id, jti=model.jti, expires_at=model.expires_at)
