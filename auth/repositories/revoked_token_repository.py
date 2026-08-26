from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth.entities.revoked_token import RevokedToken
from auth.models.revoked_token_model import RevokedTokenModel
from core.database import force_primary_var


class RevokedTokenRepository:
    def __init__(self, db) -> None:
        self.db: AsyncSession = db

    async def add(
        self, jti: str, expires_at: datetime, auto_commit: bool = True
    ) -> RevokedToken:
        force_primary_var.set(True)
        model = RevokedTokenModel(jti=jti, expires_at=expires_at)

        try:
            async with self.db.begin_nested():
                self.db.add(model)
                await self.db.flush()
        except IntegrityError as err:
            raise ValueError("Token already used") from err

        if auto_commit:
            await self.db.commit()
            await self.db.refresh(model)

        return self._to_entity(model)

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

    @staticmethod
    def _to_entity(model: RevokedTokenModel) -> RevokedToken:
        return RevokedToken(id=model.id, jti=model.jti, expires_at=model.expires_at)
