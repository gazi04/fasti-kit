from uuid import UUID

from fastapi_pagination.cursor import CursorPage, CursorParams
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio.session import AsyncSession

from core.database import force_primary_var
from user.entities.user import User
from user.models import UserModel


class UserRepository:
    def __init__(self, db) -> None:
        self.db: AsyncSession = db

    async def add(
        self,
        full_name: str,
        email: str,
        password_hash: str,
        auto_commit: bool = True,
    ) -> User:
        force_primary_var.set(True)
        model = UserModel(full_name=full_name, email=email, password_hash=password_hash)

        await self._flush_or_raise(model)

        if auto_commit:
            await self.db.commit()
            await self.db.refresh(model)

        return self._to_entity(model)

    async def get(self, id: UUID) -> User | None:
        result = await self.db.scalar(select(UserModel).where(UserModel.id == id))

        if result is None:
            return

        return self._to_entity(result)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.scalar(select(UserModel).where(UserModel.email == email))

        if not result:
            return

        return self._to_entity(result)

    async def update(self, id: UUID, auto_commit: bool = True, **fields) -> User | None:
        force_primary_var.set(True)
        user = await self.db.get(UserModel, id)

        if user is None:
            return

        for key, value in fields.items():
            setattr(user, key, value)

        if auto_commit:
            await self._flush_or_raise()
            await self.db.commit()
            await self.db.refresh(user)
        else:
            await self._flush_or_raise()

        return self._to_entity(user)

    async def delete(self, id: UUID, auto_commit: bool = True) -> User | None:
        force_primary_var.set(True)
        user = await self.db.get(UserModel, id)

        if user is None:
            return

        user.is_active = False

        if auto_commit:
            await self.db.commit()
            await self.db.refresh(user)
        else:
            await self.db.flush()

        return self._to_entity(user)

    async def force_delete(self, id: UUID, auto_commit: bool = True) -> User | None:
        force_primary_var.set(True)
        user = await self.db.get(UserModel, id)

        if user is None:
            return
        result = self._to_entity(user)

        await self.db.delete(user)

        if auto_commit:
            await self.db.commit()
        else:
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

    async def _flush_or_raise(self, model: UserModel | None = None) -> None:
        """Flush inside a SAVEPOINT so a constraint violation stays contained.

        The old _commit_or_raise() called db.rollback() on IntegrityError —
        transaction-wide, which would destroy a caller-owned transaction on a
        duplicate email.

        `model` is added *inside* the savepoint on purpose. A pending object
        added beforehand belongs to the outer SessionTransaction, and a flush
        failure then deactivates that outer transaction too — every later
        statement raises PendingRollbackError, which is exactly what the
        savepoint was supposed to prevent.
        """
        try:
            async with self.db.begin_nested():
                if model is not None:
                    self.db.add(model)
                await self.db.flush()
        except IntegrityError as err:
            if "email" in str(err.orig).lower():
                raise ValueError("Email taken") from err
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
