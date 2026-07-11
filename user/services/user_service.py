from typing import Optional
from uuid import UUID

from auth.services.security_service import SecurityService
from user.entities.user import User
from user.repositories.user_repository import UserRepository
from user.schemas.user_schema import CreateUserRequest, GetUserRequest, UpdateUserRequest


class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

    async def register(self, data: CreateUserRequest) -> User:
        password_hash = SecurityService.hash_password(data.password)
        return await self.repo.add(data.name, data.email, password_hash)

    async def get_by_email(self, data: GetUserRequest) -> Optional[User]:
        return await self.repo.get_by_email(data.email)

    async def update(self, user_id: UUID, data: UpdateUserRequest) -> Optional[User]:
        data.password = SecurityService.hash_password(data.password) if data.password else None
        return await self.repo.update(id=user_id, **data.model_dump(exclude_unset=True))
