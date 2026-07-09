from typing import AsyncGenerator

from fastapi import APIRouter, Depends

from core.database import get_db
from user.repositories.user_repository import UserRepository
from user.schemas.user_schema import CreateUserRequest, GetUserRequest
from user.services.user_service import UserService

user_router = APIRouter(prefix="/user", tags=["User"])

@user_router.post("/create")
async def create_user(data: CreateUserRequest, db: AsyncGenerator = Depends(get_db)):
    service = UserService(UserRepository(db))
    return await service.register(data)

@user_router.get('/get')
async def get_user(data: GetUserRequest, db: AsyncGenerator = Depends(get_db)):
    service = UserService(UserRepository(db))
    return await service.get_by_email(data)
