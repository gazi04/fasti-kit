from typing import AsyncGenerator

from fastapi import APIRouter, Depends

from core.database import get_db
from user.repositories.user_repository import UserRepository
from user.schemas.user_schema import UserCreate
from user.services.user_service import UserService

user_router = APIRouter(prefix="/user", tags=["User"])

@user_router.post("/create")
async def create_book(data: UserCreate, db: AsyncGenerator = Depends(get_db)):
    repo = UserRepository(db)
    service = UserService(repo)
    return await service.register(data)
