from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import UUID

from authx import TokenPayload
from fastapi import APIRouter, Depends, HTTPException, Request, Response
import jwt

from auth.dependencies import auth
from auth.repositories.revoked_token_repository import RevokedTokenRepository
from auth.schemas.auth_schema import LoginRequest, LoginResponse
from auth.services.email_verfication_service import EmailVerficationService
from auth.services.security_service import SecurityService
from auth.services.token_service import TokenService
from core.limiter import limiter
from core.database import get_db
from user.repositories.user_repository import UserRepository


auth_router = APIRouter(prefix="/auth", tags=["Auth"])


@auth_router.post("/login")
@limiter.limit("5/minute")
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncGenerator = Depends(get_db),
) -> LoginResponse:
    user = await UserRepository(db).get_by_email(data.email)

    if (
        user is None
        or not user.is_active
        or not user.is_verified
        or not SecurityService.check_password(data.password, user.password_hash)
    ):
        raise HTTPException(401, detail="Invalid credentials")

    token = auth.create_access_token(uid=str(user.id))
    refresh_token = auth.create_refresh_token(uid=str(user.id))

    auth.set_refresh_cookies(refresh_token, response)

    return LoginResponse(access_token=token)


@auth_router.get("/protected")
async def protected(
    payload: TokenPayload = Depends(
        auth.token_required(type="access", locations=["headers"])
    ),
):
    return {"user": payload.sub}


@auth_router.post("/refresh")
async def refresh(
    db: AsyncGenerator = Depends(get_db),
    payload: TokenPayload = Depends(
        auth.token_required(type="refresh", locations=["cookies"])
    ),
) -> LoginResponse:
    user = await UserRepository(db).get(UUID(payload.sub))

    if user is None or not user.is_active or not user.is_verified:
        raise HTTPException(401, detail="Invalid credentials")

    new_access_token = auth.create_access_token(uid=payload.sub)
    return LoginResponse(access_token=new_access_token)


@auth_router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    payload: TokenPayload = Depends(
        auth.token_required(type="access", locations=["headers"])
    ),
    db: AsyncGenerator = Depends(get_db),
) -> dict:
    await TokenService.revoke_tokens(request, payload, db)
    auth.unset_refresh_cookies(response)
    return {"message": "Logged out"}

@auth_router.get("/verify-email")
async def verify_email(token: str, db: AsyncGenerator = Depends(get_db)) -> dict:
    try:
        payload = await EmailVerficationService.decode_verification_token(token)
    except (jwt.PyJWKError, jwt.InvalidSignatureError):
        raise HTTPException(400, detail="Invalid verification token")

    if payload.get("purpose") != "email_verify":
        raise HTTPException(400, detail="Invalid verification token")

    token_repo = RevokedTokenRepository(db)
    if await token_repo.exists(payload['jti']):
        raise HTTPException(400, detail="Verification link already used")

    user_repo = UserRepository(db)
    user = await user_repo.get(UUID(payload['sub']))
    if user is None:
        raise HTTPException(404, detail="User not found")

    await user_repo.update(id=user.id, is_verified=True)

    expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    await token_repo.add(payload["jti"], expires_at)
    return {"message": "Email verified"}
