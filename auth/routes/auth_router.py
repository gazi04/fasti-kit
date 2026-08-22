from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt
from authx import TokenPayload
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import auth, get_revoked_token_repository, require_scopes
from auth.repositories.revoked_token_repository import RevokedTokenRepository
from auth.schemas.auth_schema import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
)
from auth.services.email_verification_service import (
    VERIFY_TYPE,
    EmailVerificationService,
)
from auth.services.password_reset_service import RESET_TYPE, PasswordResetService
from auth.services.security_service import SecurityService
from auth.services.token_service import TokenService
from core.database import force_primary_var, get_db
from core.deprecation import DeprecationRoute, deprecated
from core.limiter import limiter
from core.openapi import problem_responses
from user.dependencies import get_user_repository
from user.repositories.user_repository import UserRepository

auth_router = APIRouter(prefix="/auth", tags=["Auth"], route_class=DeprecationRoute)

# Precomputed once at import time so a login for a nonexistent/inactive/
# unverified account still pays the same bcrypt cost as a real password
# check — otherwise response timing leaks account-state to an attacker.
_DUMMY_PASSWORD_HASH = SecurityService.hash_password(uuid4().hex)


@auth_router.post("/login", responses=problem_responses(401, 422, 500))
@limiter.limit("5/minute")
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    user_repository: UserRepository = Depends(get_user_repository),
) -> LoginResponse:
    force_primary_var.set(True)
    user = await user_repository.get_by_email(data.email)

    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_ok = SecurityService.check_password(data.password, password_hash)

    if user is None or not password_ok or not user.is_active or not user.is_verified:
        raise HTTPException(401, detail="Invalid credentials")

    token = auth.create_access_token(uid=str(user.id), scopes=user.scopes.split())
    refresh_token = auth.create_refresh_token(uid=str(user.id))

    auth.set_refresh_cookies(refresh_token, response)

    return LoginResponse(access_token=token)


@auth_router.get("/protected")
async def protected(
    payload: TokenPayload = Depends(require_scopes("admin:read")),
):
    return {"user": payload.sub}


@auth_router.post("/refresh")
@limiter.limit("5/minute")
async def refresh(
    request: Request,
    user_repo: UserRepository = Depends(get_user_repository),
    payload: TokenPayload = Depends(
        auth.token_required(type="refresh", locations=["cookies"])
    ),
) -> LoginResponse:
    force_primary_var.set(True)
    user = await user_repo.get(UUID(payload.sub))

    if user is None or not user.is_active or not user.is_verified:
        raise HTTPException(401, detail="Invalid credentials")

    new_access_token = auth.create_access_token(
        uid=payload.sub, scopes=user.scopes.split()
    )
    return LoginResponse(access_token=new_access_token)


@auth_router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    payload: TokenPayload = Depends(
        auth.token_required(type="access", locations=["headers"])
    ),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await TokenService.revoke_tokens(request, payload, db)
    auth.unset_refresh_cookies(response)
    return {"message": "Logged out"}


@auth_router.get("/verify-email")
@limiter.limit("5/minute")
async def verify_email(
    token: str,
    request: Request,
    user_repo: UserRepository = Depends(get_user_repository),
    token_repo: RevokedTokenRepository = Depends(get_revoked_token_repository),
    db: AsyncSession = Depends(get_db),
) -> dict:
    force_primary_var.set(True)
    try:
        payload = await EmailVerificationService.decode_verification_token(token)
    except jwt.PyJWTError as err:
        raise HTTPException(400, detail="Invalid or expired verification link") from err

    if payload.get("type") != VERIFY_TYPE:
        raise HTTPException(400, detail="Invalid verification token")

    if await token_repo.exists(payload["jti"]):
        raise HTTPException(400, detail="Verification link already used")

    user = await user_repo.get(UUID(payload["sub"]))
    if user is None:
        raise HTTPException(404, detail="User not found")

    if user.pending_verification_jti != payload["jti"]:
        raise HTTPException(
            400, detail="Verification link has been superseded by a newer request"
        )

    await user_repo.update(id=user.id, is_verified=True, auto_commit=False)

    expires_at = datetime.fromtimestamp(payload["exp"], tz=UTC)

    try:
        await token_repo.add(payload["jti"], expires_at, auto_commit=False)
        await db.commit()
    except (ValueError, IntegrityError) as err:
        await db.rollback()
        raise HTTPException(400, detail="Verification link already used") from err

    return {"message": "Email verified"}


@auth_router.post("/resend-verification")
@limiter.limit("5/minute")
async def resend_verification(
    data: ResendVerificationRequest,
    request: Request,
    background_task: BackgroundTasks,
    user_repo: UserRepository = Depends(get_user_repository),
) -> dict:
    user = await user_repo.get_by_email(data.email)

    if user is not None and not user.is_verified:
        token, pending_jti = EmailVerificationService.create_verification_token(
            str(user.id)
        )
        await user_repo.update(user.id, pending_verification_jti=pending_jti)
        background_task.add_task(
            EmailVerificationService.send_verification_email, user.email, token
        )

    return {
        "message": (
            "If an account with that email exists and is unverified, "
            "a verification link has been sent."
        )
    }


@auth_router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    background_task: BackgroundTasks,
    user_repo: UserRepository = Depends(get_user_repository),
) -> dict:
    user = await user_repo.get_by_email(data.email)

    if user is not None and user.is_active:
        token, jti = PasswordResetService.create_reset_token(str(user.id))
        await user_repo.update(user.id, pending_password_reset_jti=jti)
        background_task.add_task(
            PasswordResetService.send_reset_email, user.email, token
        )

    return {
        "message": (
            "If an account with that email exists, a password reset link has been sent."
        )
    }


@auth_router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(
    data: ResetPasswordRequest,
    request: Request,
    user_repo: UserRepository = Depends(get_user_repository),
    token_repo: RevokedTokenRepository = Depends(get_revoked_token_repository),
    db: AsyncSession = Depends(get_db),
) -> dict:
    force_primary_var.set(True)
    try:
        payload = await PasswordResetService.decode_reset_token(data.token)
    except jwt.PyJWTError as err:
        raise HTTPException(400, detail="Invalid or expired reset link") from err

    if payload.get("type") != RESET_TYPE:
        raise HTTPException(400, detail="Invalid reset token")

    if await token_repo.exists(payload["jti"]):
        raise HTTPException(400, detail="Reset link already used")

    user = await user_repo.get(UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(404, detail="User not found")

    if user.pending_password_reset_jti != payload["jti"]:
        raise HTTPException(
            400, detail="Reset link has been superseded by a newer request"
        )

    new_hash = SecurityService.hash_password(data.new_password)
    await user_repo.update(id=user.id, password_hash=new_hash, auto_commit=False)

    expires_at = datetime.fromtimestamp(payload["exp"], tz=UTC)
    try:
        await token_repo.add(payload["jti"], expires_at, auto_commit=False)
        await db.commit()
    except (ValueError, IntegrityError) as err:
        await db.rollback()
        raise HTTPException(400, detail="Reset link already used") from err

    return {"message": "Password has been reset"}


@auth_router.get("/deprecated-endpoint")
@deprecated(sunset="Sat, 01 Jan 2027 00:00:00 GMT")
async def deprecated_endpoint():
    """
    Handles legacy authentication.

    **SUNSET DATE:** Sat, 01 Jan 2027 00:00:00 GMT - Please migrate
    to /api/v1/auth/refresh.
    """
    ...
