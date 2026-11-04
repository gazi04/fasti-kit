from uuid import UUID

from authx import TokenPayload
from fastapi import (
    APIRouter,
    Depends,
    Request,
    Response,
)

from auth.dependencies import (
    auth,
    get_auth_service,
    get_auth_session,
    refresh_session_claims,
)
from auth.entities.auth_session import AuthSession
from auth.entities.refresh_session import RefreshSession
from auth.exceptions import InvalidRefreshTokenError
from auth.schemas.auth_schema import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
)
from auth.services.auth_service import AuthService
from core.limiter import limiter
from core.openapi import problem_responses

auth_router = APIRouter(prefix="/auth", tags=["Auth"])


def _set_refresh_cookie(user_id: str, session: RefreshSession, response: Response):
    refresh_token = auth.create_refresh_token(
        uid=user_id,
        expiry=session.expires_at,
        data={"sid": str(session.id), "gen": session.generation},
    )
    auth.set_refresh_cookies(refresh_token, response)


@auth_router.post("/login", responses=problem_responses(401, 422, 500))
@limiter.limit("5/minute")
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    user, session = await service.login(data.email, data.password)

    token = auth.create_access_token(uid=str(user.id), scopes=user.scope_list)
    _set_refresh_cookie(str(user.id), session, response)

    return LoginResponse(access_token=token)


@auth_router.post("/refresh", responses=problem_responses(401, 409, 500))
@limiter.limit("5/minute")
async def refresh(
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    payload: TokenPayload = Depends(
        auth.token_required(type="refresh", locations=["cookies"])
    ),
) -> LoginResponse:
    claims = refresh_session_claims(payload)
    if claims is None:
        raise InvalidRefreshTokenError

    user, session = await service.refresh(UUID(payload.sub), *claims)

    new_access_token = auth.create_access_token(uid=payload.sub, scopes=user.scope_list)
    _set_refresh_cookie(payload.sub, session, response)
    return LoginResponse(access_token=new_access_token)


@auth_router.post("/logout")
async def logout(
    response: Response,
    service: AuthService = Depends(get_auth_service),
    session: AuthSession = Depends(get_auth_session),
) -> dict:
    await service.logout(session)
    auth.unset_refresh_cookies(response)
    return {"message": "Logged out"}


@auth_router.get("/verify-email")
@limiter.limit("5/minute")
async def verify_email(
    token: str,
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> dict:
    await service.verify_email(token)
    return {"message": "Email verified"}


@auth_router.post("/resend-verification")
@limiter.limit("5/minute")
async def resend_verification(
    data: ResendVerificationRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> dict:
    await service.resend_verification(data.email)
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
    service: AuthService = Depends(get_auth_service),
) -> dict:
    await service.forgot_password(data.email)
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
    service: AuthService = Depends(get_auth_service),
) -> dict:
    await service.reset_password(data.token, data.new_password)
    return {"message": "Password has been reset"}
