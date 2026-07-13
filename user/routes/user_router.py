from typing import AsyncGenerator, Optional
from uuid import UUID

from authx import TokenPayload
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response

from auth.dependencies import auth
from auth.services.email_verfication_service import EmailVerficationService
from auth.services.token_service import TokenService
from core.database import get_db
from user.entities.user import User
from user.repositories.user_repository import UserRepository
from user.schemas.user_schema import (
    CreateUserRequest,
    GetUserRequest,
    UserResponse,
    UpdateUserRequest,
)
from user.services.user_service import UserService

user_router = APIRouter(prefix="/user", tags=["User"])


@user_router.post("/create", response_model=UserResponse)
async def create_user(
        data: CreateUserRequest, background_tasks: BackgroundTasks, db: AsyncGenerator = Depends(get_db)
) -> User:
    user_repo = UserRepository(db)
    service = UserService(user_repo)

    try:
        user = await service.register(data)
    except ValueError:
        raise HTTPException(409, "Email already in use")

    token, jti = EmailVerficationService.create_verification_token(str(user.id))

    try:
        await user_repo.update(user.id, pending_verification_jti=jti)
    except Exception:
        raise HTTPException(500, detail="Failed to schedule verification email")

    background_tasks.add_task(EmailVerficationService.send_verification_email, user.email, token)
    return user


@user_router.get("/get", response_model=UserResponse)
async def get_user(
    data: GetUserRequest,
    db: AsyncGenerator = Depends(get_db),
    payload: TokenPayload = Depends(
        auth.token_required(type="access", locations=["headers"])
    ),
) -> Optional[User]:
    service = UserService(UserRepository(db))
    user = await service.get_by_email(data)

    if user is None:
        raise HTTPException(404, "User not found")

    return user


@user_router.patch("/update", response_model=UserResponse)
async def update_user(
    data: UpdateUserRequest,
    db: AsyncGenerator = Depends(get_db),
    payload: TokenPayload = Depends(
        auth.token_required(type="access", locations=["headers"])
    ),
):
    user_id = UUID(payload.sub)
    service = UserService(UserRepository(db))

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
    db: AsyncGenerator = Depends(get_db),
    payload: TokenPayload = Depends(
        auth.token_required(type="access", locations=["headers"])
    ),
):
    user_id = UUID(payload.sub)
    deleted = await UserService(UserRepository(db)).delete(user_id)

    if deleted is None:
        raise HTTPException(404, "User not found")

    await TokenService.revoke_tokens(request, payload, db)
    auth.unset_refresh_cookies(response)
    return {"message": "User deleted"}
