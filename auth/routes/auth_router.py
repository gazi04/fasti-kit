from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import UUID

from authx import TokenPayload
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
import jwt

from auth.dependencies import auth
from auth.repositories.revoked_token_repository import RevokedTokenRepository
from auth.schemas.auth_schema import LoginRequest, LoginResponse, ResendVerficationRequest
from auth.services.email_verification_service import VERIFY_TYPE, EmailVerificationService
from auth.services.security_service import SecurityService
from auth.services.token_service import TokenService
from core.limiter import limiter
from core.database import get_db
from user.repositories.user_repository import UserRepository

# TODO: add reset and verify email operations

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
@limiter.limit("5/minute")
async def refresh(
    request: Request,
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
@limiter.limit("5/minute")
async def verify_email(token: str, request: Request, db: AsyncGenerator = Depends(get_db)) -> dict:
    try:
        payload = await EmailVerificationService.decode_verification_token(token)
    except jwt.PyJWTError:
        raise HTTPException(400, detail="Invalid or expired verification link")

    if payload.get("type") != VERIFY_TYPE:
        raise HTTPException(400, detail="Invalid verification token")

    token_repo = RevokedTokenRepository(db)
    if await token_repo.exists(payload['jti']):
        raise HTTPException(400, detail="Verification link already used")

    user_repo = UserRepository(db)
    user = await user_repo.get(UUID(payload['sub']))
    if user is None:
        raise HTTPException(404, detail="User not found")

    if user.pending_verification_jti != payload['jti']:
        raise HTTPException(400, detail="Verification link has been superseded by a newer request")

    await user_repo.update(id=user.id, is_verified=True)

    expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

    try:
        await token_repo.add(payload["jti"], expires_at)
    except ValueError:
        raise HTTPException(400, detail="Verification link already used")

    return {"message": "Email verified"}


@auth_router.post("/resend-verification")
@limiter.limit("5/minute")
async def resend_verification(data: ResendVerficationRequest, request: Request, background_task: BackgroundTasks, db: AsyncGenerator = Depends(get_db)) -> dict:
    user_repo = UserRepository(db)
    user = await user_repo.get_by_email(data.email)

    if user is not None and not user.is_verified:
        token, pending_jti = EmailVerificationService.create_verification_token(str(user.id))
        await user_repo.update(user.id, pending_verification_jti=pending_jti)
        background_task.add_task(EmailVerificationService.send_verification_email, user.email, token)

    return {"message": "If an account with that email exists and is unverified, a verification link has been sent."}
