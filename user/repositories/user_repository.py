from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio.session import AsyncSession

from user.entities.user import User
from user.models import UserModel

class UserRepository:
    def __init__(self, db) -> None:
        self.db: AsyncSession = db

    async def add(self, full_name: str, email: str, password_hash: str) -> User:
        model = UserModel(full_name=full_name, email=email, password_hash=password_hash)
        self.db.add(model)
        await self.db.commit()
        await self.db.refresh(model)
        return self._to_entity(model)

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.db.scalar(select(UserModel).where(UserModel.email == email))

        if not result:
            return

        return self._to_entity(result)

    @staticmethod
    def _to_entity(model: UserModel) -> User:
        return User(id=model.id, email=model.email, full_name=model.full_name, password_hash=model.password_hash, is_active=model.is_active, created_at=model.created_at, updated_at=model.updated_at)
