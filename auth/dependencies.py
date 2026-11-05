import contextlib
from datetime import timedelta
from typing import Any
from uuid import UUID

from authx import AuthX, AuthXConfig, JWTDecodeError, TokenPayload
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from auth.blocklist import TokenBlocklist
from auth.entities.auth_session import AuthSession, TokenRef
from auth.repositories.account_repository import AccountRepository
from auth.repositories.refresh_session_repository import RefreshSessionRepository
from auth.repositories.revoked_token_repository import RevokedTokenRepository
from auth.services.auth_service import AuthService
from core.database import AsyncSessionLocal, get_db
from core.exception import UnauthorizedActionError
from core.redis import redis
from core.setting import get_settings
from user.repositories.user_repository import UserRepository

settings = get_settings()

config = AuthXConfig(
    JWT_SECRET_KEY=settings.jwt_secret_key,
    JWT_ALGORITHM=settings.jwt_algorithm,
    JWT_TOKEN_LOCATION=["headers", "cookies"],
    JWT_COOKIE_SECURE=settings.jwt_cookie_secure,
    JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=settings.jwt_refresh_token_ttl_days),
    JWT_COOKIE_HTTP_ONLY=True,  # Prevent JS access
    JWT_COOKIE_CSRF_PROTECT=True,  # CSRF protection for refresh
)

auth = AuthX(config=config)
blocklist = TokenBlocklist(redis)


async def is_token_revoked(token: str, **kwargs: Any) -> bool:
    payload = TokenPayload.decode(
        token,
        key=settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        verify=True,
    )
    if payload.jti is None:
        return True

    cached = await blocklist.lookup(payload.jti)
    if cached is not None:
        return cached

    async with AsyncSessionLocal() as db:
        repo = RevokedTokenRepository(db)
        revoked = await repo.exists(payload.jti)
        if await blocklist.claim_seeding():
            await blocklist.seed(await repo.list_active())

    return revoked


def get_revoked_token_repository(
    db: AsyncSession = Depends(get_db),
) -> RevokedTokenRepository:
    return RevokedTokenRepository(db)


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(
        UserRepository(db),
        AccountRepository(db),
        RevokedTokenRepository(db),
        RefreshSessionRepository(db),
        blocklist,
        session_ttl=timedelta(days=settings.jwt_refresh_token_ttl_days),
        reuse_grace=timedelta(seconds=settings.refresh_reuse_grace_seconds),
    )


def refresh_session_claims(payload: TokenPayload) -> tuple[UUID, int] | None:
    claims = payload.model_extra or {}
    try:
        return UUID(claims["sid"]), int(claims["gen"])
    except (KeyError, TypeError, ValueError):
        return None


def get_auth_session(
    request: Request,
    payload: TokenPayload = Depends(
        auth.token_required(type="access", locations=["headers"])
    ),
) -> AuthSession:
    tokens: list[TokenRef] = []
    refresh_session_id: UUID | None = None

    if payload.jti is not None:
        tokens.append(TokenRef(payload.jti, payload.expiry_datetime))

    refresh_token = request.cookies.get(auth.config.JWT_REFRESH_COOKIE_NAME)
    if refresh_token:
        with contextlib.suppress(JWTDecodeError):
            refresh_payload = TokenPayload.decode(
                refresh_token,
                key=settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
                verify=True,
            )
            if refresh_payload.jti is not None:
                tokens.append(
                    TokenRef(refresh_payload.jti, refresh_payload.expiry_datetime)
                )
            claims = refresh_session_claims(refresh_payload)
            if claims is not None:
                refresh_session_id = claims[0]

    return AuthSession(
        user_id=UUID(payload.sub),
        tokens=tokens,
        refresh_session_id=refresh_session_id,
    )


def require_scopes(*required: str, all_required: bool = True):
    async def _check(
        payload: TokenPayload = Depends(
            auth.token_required(type="access", locations=["headers"])
        ),
    ) -> TokenPayload:
        if not payload.has_scopes(*required, all_required=all_required):
            raise UnauthorizedActionError("Insufficient permissions")
        return payload

    return _check


auth.set_callback_token_blocklist(is_token_revoked)
