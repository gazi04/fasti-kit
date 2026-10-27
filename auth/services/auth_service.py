from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import jwt

from auth.entities.auth_session import TokenRef
from auth.exceptions import InvalidCredentialsError, InvalidTokenError
from auth.repositories.account_repository import AccountRepository
from auth.repositories.revoked_token_repository import RevokedTokenRepository
from auth.services.email_verification_service import (
    VERIFY_TYPE,
    EmailVerificationService,
)
from auth.services.password_reset_service import RESET_TYPE, PasswordResetService
from auth.services.security_service import SecurityService
from core.cache import invalidate_tags
from core.exception import ConflictError, EntityNotFoundError
from user.entities.user import User
from user.repositories.user_repository import UserRepository


class AuthService:
    def __init__(
        self,
        user_repo: UserRepository,
        account_repo: AccountRepository,
        token_repo: RevokedTokenRepository,
    ) -> None:
        self.user_repo = user_repo
        self.account_repo = account_repo
        self.token_repo = token_repo

    async def login(self, email: str, password: str) -> User:
        user = await SecurityService.authenticate(email, password, self.user_repo)

        if user is None:
            raise InvalidCredentialsError

        return user

    async def refresh(self, user_id: UUID) -> User:
        user = await self.user_repo.get(user_id, consistent=True)

        if user is None or not user.is_active or not user.is_verified:
            raise InvalidCredentialsError

        return user

    async def logout(self, tokens: Sequence[TokenRef]) -> None:
        await self.account_repo.revoke_tokens(tokens)

    async def close_account(self, user_id: UUID, tokens: Sequence[TokenRef]) -> None:
        user = await self.account_repo.close_account(user_id, tokens)

        if user is None:
            raise EntityNotFoundError("User", str(user_id))

        await invalidate_tags("users")

    async def verify_email(self, token: str) -> None:
        payload = await self._decode(
            token,
            decode=EmailVerificationService.decode_verification_token,
            expected_type=VERIFY_TYPE,
            invalid="Invalid or expired verification link",
            wrong_type="Invalid verification token",
            used="Verification link already used",
        )
        user = await self._user_for_token(payload)

        if user.pending_verification_jti != payload["jti"]:
            raise InvalidTokenError(
                "Verification link has been superseded by a newer request"
            )

        try:
            await self.account_repo.verify_email(
                user.id, payload["jti"], self._expiry(payload)
            )
        except ConflictError as err:
            raise InvalidTokenError("Verification link already used") from err

    async def resend_verification(self, email: str) -> None:
        user = await self.user_repo.get_by_email(email)

        if user is None or user.is_verified:
            return

        token, jti = EmailVerificationService.create_verification_token(str(user.id))
        await self.account_repo.start_email_verification(
            user.id, jti, EmailVerificationService.build_email_payload(email, token)
        )

    async def forgot_password(self, email: str) -> None:
        user = await self.user_repo.get_by_email(email)

        if user is None or not user.is_active:
            return

        token, jti = PasswordResetService.create_reset_token(str(user.id))
        await self.account_repo.start_password_reset(
            user.id, jti, PasswordResetService.build_email_payload(email, token)
        )

    async def reset_password(self, token: str, new_password: str) -> None:
        payload = await self._decode(
            token,
            decode=PasswordResetService.decode_reset_token,
            expected_type=RESET_TYPE,
            invalid="Invalid or expired reset link",
            wrong_type="Invalid reset token",
            used="Reset link already used",
        )
        user = await self._user_for_token(payload)

        if not user.is_active:
            raise EntityNotFoundError("User", str(user.id))
        if user.pending_password_reset_jti != payload["jti"]:
            raise InvalidTokenError("Reset link has been superseded by a newer request")

        try:
            await self.account_repo.reset_password(
                user.id,
                SecurityService.hash_password(new_password),
                payload["jti"],
                self._expiry(payload),
            )
        except ConflictError as err:
            raise InvalidTokenError("Reset link already used") from err

    async def _decode(
        self,
        token: str,
        *,
        decode: Callable[[str], Awaitable[dict[str, Any]]],
        expected_type: str,
        invalid: str,
        wrong_type: str,
        used: str,
    ) -> dict[str, Any]:
        try:
            payload = await decode(token)
        except jwt.PyJWTError as err:
            raise InvalidTokenError(invalid) from err

        if payload.get("type") != expected_type:
            raise InvalidTokenError(wrong_type)
        if await self.token_repo.exists(payload["jti"]):
            raise InvalidTokenError(used)

        return payload

    async def _user_for_token(self, payload: dict[str, Any]) -> User:
        user = await self.user_repo.get(UUID(payload["sub"]), consistent=True)

        if user is None:
            raise EntityNotFoundError("User", payload["sub"])

        return user

    @staticmethod
    def _expiry(payload: dict[str, Any]) -> datetime:
        return datetime.fromtimestamp(payload["exp"], tz=UTC)
