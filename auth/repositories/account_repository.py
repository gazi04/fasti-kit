from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from auth.entities.auth_session import TokenRef
from auth.repositories.revoked_token_repository import RevokedTokenRepository
from core.database import transaction
from core.exception import EntityNotFoundError
from core.outbox.repository import OutboxRepository
from user.entities.user import User
from user.repositories.user_repository import UserRepository


class AccountRepository:
    def __init__(self, db) -> None:
        self.db = db
        self._users = UserRepository(db)
        self._tokens = RevokedTokenRepository(db)
        self._outbox = OutboxRepository(db)

    async def verify_email(self, user_id: UUID, jti: str, expires_at: datetime) -> User:
        async with transaction(self.db):
            user = await self._users.stage_update(user_id, is_verified=True)
            if user is None:
                raise EntityNotFoundError("User", str(user_id))
            await self._tokens.stage_add(jti, expires_at)
            return user

    async def reset_password(
        self, user_id: UUID, password_hash: str, jti: str, expires_at: datetime
    ) -> User:
        async with transaction(self.db):
            user = await self._users.stage_update(user_id, password_hash=password_hash)
            if user is None:
                raise EntityNotFoundError("User", str(user_id))
            await self._tokens.stage_add(jti, expires_at)
            return user

    async def start_email_verification(
        self, user_id: UUID, jti: str, email_payload: dict[str, Any]
    ) -> None:
        async with transaction(self.db):
            user = await self._users.stage_update(user_id, pending_verification_jti=jti)
            if user is None:
                raise EntityNotFoundError("User", str(user_id))
            await self._outbox.stage_add("send_email_task", email_payload)

    async def start_password_reset(
        self, user_id: UUID, jti: str, email_payload: dict[str, Any]
    ) -> None:
        async with transaction(self.db):
            user = await self._users.stage_update(
                user_id, pending_password_reset_jti=jti
            )
            if user is None:
                raise EntityNotFoundError("User", str(user_id))
            await self._outbox.stage_add("send_email_task", email_payload)

    async def revoke_tokens(self, tokens: Sequence[TokenRef]) -> None:
        async with transaction(self.db):
            for token in tokens:
                await self._tokens.stage_add_if_absent(token.jti, token.expires_at)

    async def close_account(
        self, user_id: UUID, tokens: Sequence[TokenRef]
    ) -> User | None:
        async with transaction(self.db):
            user = await self._users.stage_deactivate(user_id)
            if user is None:
                return None
            for token in tokens:
                await self._tokens.stage_add_if_absent(token.jti, token.expires_at)
            return user
