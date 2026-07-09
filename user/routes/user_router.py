from typing import AsyncGenerator, Optional

from authx import TokenPayload
from fastapi import APIRouter, Depends, HTTPException

from auth.dependencies import auth
from core.database import get_db
from user.entities.user import User
from user.repositories.user_repository import UserRepository
from user.schemas.user_schema import CreateUserRequest, GetUserRequest, UserResponse
from user.services.user_service import UserService

user_router = APIRouter(prefix="/user", tags=["User"])

@user_router.post("/create", response_model=UserResponse)
async def create_user(data: CreateUserRequest, db: AsyncGenerator = Depends(get_db)) -> User:
    service = UserService(UserRepository(db))
    return await service.register(data)

@user_router.get('/get', response_model=UserResponse)
async def get_user(
        data: GetUserRequest,
        db: AsyncGenerator = Depends(get_db),
        payload: TokenPayload = Depends(auth.token_required(type='access', locations=['headers']))
    ) -> Optional[User]:
    service = UserService(UserRepository(db))
    user = await service.get_by_email(data)

    if user is None:
        raise HTTPException(404, 'User not found')

    return user
