from typing import Optional
from uuid import UUID

from authx import TokenPayload
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import auth
from auth.services.email_verification_service import EmailVerificationService
from auth.services.token_service import TokenService
from core.limiter import limiter
from core.database import get_db
from user.dependencies import get_user_repository, get_user_service
from user.entities.user import User
from user.repositories.user_repository import UserRepository
from user.schemas.user_schema import (
    CreateUserRequest,
    UserResponse,
    UpdateUserRequest,
)
from user.services.user_service import UserService

user_router = APIRouter(prefix="/user", tags=["User"])


@user_router.post("/create", response_model=UserResponse)
@limiter.limit("5/minute")
async def create_user(
    data: CreateUserRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user_repo: UserRepository = Depends(get_user_repository),
    service: UserService = Depends(get_user_service)
) -> User:
    try:
        user = await service.register(data)
    except ValueError:
        raise HTTPException(409, "Email already in use")

    token, jti = EmailVerificationService.create_verification_token(str(user.id))

    try:
        await user_repo.update(user.id, pending_verification_jti=jti)
    except Exception:
        raise HTTPException(500, detail="Failed to schedule verification email")

    background_tasks.add_task(
        EmailVerificationService.send_verification_email, user.email, token
    )
    return user


@user_router.get("/get", response_model=UserResponse)
async def get_user(
    service: UserService = Depends(get_user_service),
    payload: TokenPayload = Depends(
        auth.token_required(type="access", locations=["headers"])
    ),
) -> Optional[User]:
    user_id = UUID(payload.sub)
    user = await service.get(user_id)

    if user is None:
        raise HTTPException(404, "User not found")

    return user


@user_router.patch("/update", response_model=UserResponse)
async def update_user(
    data: UpdateUserRequest,
    service: UserService = Depends(get_user_service),
    payload: TokenPayload = Depends(
        auth.token_required(type="access", locations=["headers"])
    ),
):
    user_id = UUID(payload.sub)

    try:
        user = await service.update(user_id, data)
    except ValueError:
        raise HTTPException(409, "Email already in use")

    if user is None:
        raise HTTPException(404, "User not found")

    return user


@user_router.delete("/delete")
async def delete_user(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    service: UserService = Depends(get_user_service),
    payload: TokenPayload = Depends(
        auth.token_required(type="access", locations=["headers"])
    ),
):
    user_id = UUID(payload.sub)
    deleted = await service.delete(user_id)

    if deleted is None:
        raise HTTPException(404, "User not found")

    await TokenService.revoke_tokens(request, payload, db)
    auth.unset_refresh_cookies(response)
    return {"message": "User deleted"}
