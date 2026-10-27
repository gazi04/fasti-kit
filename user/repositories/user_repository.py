from typing import Any
from uuid import UUID, uuid4

from fastapi_pagination.cursor import CursorPage, CursorParams
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio.session import AsyncSession

from core.database import force_primary_var, transaction
from core.exception import ConflictError
from core.outbox.repository import OutboxRepository
from user.entities.user import User
from user.models import UserModel


class UserRepository:
    def __init__(self, db) -> None:
        self.db: AsyncSession = db
        self._outbox = OutboxRepository(db)

    async def add(self, full_name: str, email: str, password_hash: str) -> User:
        async with transaction(self.db):
            return await self.stage_add(full_name, email, password_hash)

    async def register(
        self,
        *,
        id: UUID,
        full_name: str,
        email: str,
        password_hash: str,
        pending_verification_jti: str,
        email_payload: dict[str, Any],
    ) -> User:
        async with transaction(self.db):
            user = await self.stage_add(
                full_name,
                email,
                password_hash,
                id=id,
                pending_verification_jti=pending_verification_jti,
            )
            await self._outbox.stage_add("send_email_task", email_payload)
            return user

    async def get(self, id: UUID, *, consistent: bool = False) -> User | None:
        if consistent:
            force_primary_var.set(True)

        result = await self.db.scalar(select(UserModel).where(UserModel.id == id))

        if result is None:
            return

        return self._to_entity(result)

    async def get_by_email(
        self, email: str, *, consistent: bool = False
    ) -> User | None:
        if consistent:
            force_primary_var.set(True)

        result = await self.db.scalar(select(UserModel).where(UserModel.email == email))

        if not result:
            return

        return self._to_entity(result)

    async def update(self, id: UUID, **fields) -> User | None:
        async with transaction(self.db):
            return await self.stage_update(id, **fields)

    async def delete(self, id: UUID) -> User | None:
        async with transaction(self.db):
            return await self.stage_deactivate(id)

    async def force_delete(self, id: UUID) -> User | None:
        force_primary_var.set(True)
        user = await self.db.get(UserModel, id)

        if user is None:
            return
        result = self._to_entity(user)

        async with transaction(self.db):
            await self.db.delete(user)
            await self.db.flush()

        return result

    async def list(self, params: CursorParams | None = None) -> CursorPage[User]:
        return await apaginate(
            self.db,
            select(UserModel).order_by(
                UserModel.created_at.desc(), UserModel.id.desc()
            ),
            params=params or CursorParams(),
            transformer=lambda models: [self._to_entity(model) for model in models],
        )

    async def stage_add(
        self,
        full_name: str,
        email: str,
        password_hash: str,
        *,
        id: UUID | None = None,
        pending_verification_jti: str | None = None,
    ) -> User:
        force_primary_var.set(True)
        model = UserModel(
            id=id or uuid4(),
            full_name=full_name,
            email=email,
            password_hash=password_hash,
            pending_verification_jti=pending_verification_jti,
        )

        await self._flush_or_raise(model)

        return self._to_entity(model)

    async def stage_update(self, id: UUID, **fields) -> User | None:
        force_primary_var.set(True)
        user = await self.db.get(UserModel, id)

        if user is None:
            return

        for key, value in fields.items():
            setattr(user, key, value)

        await self._flush_or_raise()

        return self._to_entity(user)

    async def stage_deactivate(self, id: UUID) -> User | None:
        return await self.stage_update(id, is_active=False)

    async def _flush_or_raise(self, model: UserModel | None = None) -> None:
        try:
            if model is not None:
                self.db.add(model)
            await self.db.flush()
        except IntegrityError as err:
            if "email" in str(err.orig).lower():
                raise ConflictError("Email already in use") from err
            raise

    @staticmethod
    def _to_entity(model: UserModel) -> User:
        return User(
            id=model.id,
            email=model.email,
            full_name=model.full_name,
            password_hash=model.password_hash,
            scopes=model.scopes,
            is_active=model.is_active,
            is_verified=model.is_verified,
            pending_verification_jti=model.pending_verification_jti,
            pending_password_reset_jti=model.pending_password_reset_jti,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
