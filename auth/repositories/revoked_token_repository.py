from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth.entities.revoked_token import RevokedToken
from auth.models.revoked_token_model import RevokedTokenModel


class RevokedTokenRepository:
    def __init__(self, db) -> None:
        self.db: AsyncSession = db

    async def add(self, jti: str, expires_at: datetime) -> RevokedToken:
        model = RevokedTokenModel(jti=jti, expires_at=expires_at)
        self.db.add(model)

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Token already used")

        await self.db.refresh(model)
        return self._to_entity(model)

    async def exists(self, jti: str) -> bool:
        result = await self.db.scalar(
            select(RevokedTokenModel).where(
                RevokedTokenModel.jti == jti,
                RevokedTokenModel.expires_at > datetime.now(timezone.utc),
            )
        )

        return result is not None

    @staticmethod
    def _to_entity(model: RevokedTokenModel) -> RevokedToken:
        return RevokedToken(id=model.id, jti=model.jti, expires_at=model.expires_at)
