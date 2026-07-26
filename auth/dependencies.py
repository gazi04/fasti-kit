from typing import Any
from uuid import UUID

from authx import AuthX, AuthXConfig, TokenPayload
from fastapi import Depends

from auth.repositories.revoked_token_repository import RevokedTokenRepository
from core.database import AsyncSessionLocal, get_db
from core.setting import get_settings
from user.repositories import UserRepository
from user.entities import User

settings = get_settings()

config = AuthXConfig(
    JWT_SECRET_KEY=settings.jwt_secret_key,
    JWT_ALGORITHM=settings.jwt_algorithm,
    JWT_TOKEN_LOCATION=["headers", "cookies"],
    JWT_COOKIE_SECURE=settings.jwt_cookie_secure,
    JWT_COOKIE_HTTP_ONLY=True,  # Prevent JS access
    JWT_COOKIE_CSRF_PROTECT=True,  # CSRF protection for refresh
)

auth = AuthX(config=config)


async def is_token_revoked(token: str, **kwargs: Any) -> bool:
    payload = TokenPayload.decode(
        token,
        key=settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        verify=False,
    )
    if payload.jti is None:
        return True

    async with AsyncSessionLocal() as db:
        return await RevokedTokenRepository(db).exists(payload.jti)

async def get_current_user(payload = Depends(auth.token_required()), db = Depends(get_db)) -> User:
    return await UserRepository(db).get(UUID(payload.sub))

auth.set_callback_token_blocklist(is_token_revoked)
