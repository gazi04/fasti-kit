from uuid import UUID

from authx import TokenPayload
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import auth
from core.database import get_db
from user.entities.user import User
from user.repositories.user_repository import UserRepository
from user.services.user_service import UserService


def get_user_repository(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_user_service(
    repo: UserRepository = Depends(get_user_repository),
) -> UserService:
    return UserService(repo)


async def get_current_user(
    user_repo: UserRepository = Depends(get_user_repository),
    payload: TokenPayload = Depends(
        auth.token_required(type="access", locations=["headers"])
    ),
) -> User:
    user = await user_repo.get(UUID(payload.sub))

    if user is None:
        raise HTTPException(404, "User not found")
    if not user.is_active:
        raise HTTPException(403, "Account is deactivated")

    return user
