from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio.session import AsyncSession

from user.entities.user import User
from user.models import UserModel


class UserRepository:
    def __init__(self, db) -> None:
        self.db: AsyncSession = db

    async def add(self, full_name: str, email: str, password_hash: str) -> User:
        model = UserModel(full_name=full_name, email=email, password_hash=password_hash)
        self.db.add(model)

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Email taken")

        await self.db.refresh(model)
        return self._to_entity(model)

    async def get(self, id: UUID) -> Optional[User]:
        result = await self.db.scalar(select(UserModel).where(UserModel.id == id))

        if result is None:
            return

        return self._to_entity(result)

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.db.scalar(select(UserModel).where(UserModel.email == email))

        if not result:
            return

        return self._to_entity(result)

    async def update(self, id: UUID, **fields) -> Optional[User]:
        user = await self.db.get(UserModel, id)

        if user is None:
            return

        for key, value in fields.items():
            if value is None:
                continue

            setattr(user, key, value)

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Email taken")

        await self.db.refresh(user)
        return self._to_entity(user)

    async def delete(self, id: UUID) -> Optional[User]:
        user = await self.db.get(UserModel, id)

        if user is None:
            return

        user.is_active = False
        await self.db.commit()
        await self.db.refresh(user)
        return self._to_entity(user)

    async def force_delete(self, id: UUID) -> Optional[User]:
        user = await self.db.get(UserModel, id)

        if user is None:
            return
        result = self._to_entity(user)

        await self.db.delete(user)
        await self.db.commit()
        return result

    @staticmethod
    def _to_entity(model: UserModel) -> User:
        return User(
            id=model.id,
            email=model.email,
            full_name=model.full_name,
            password_hash=model.password_hash,
            is_active=model.is_active,
            is_verified=model.is_verified,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
