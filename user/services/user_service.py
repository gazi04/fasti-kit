from uuid import UUID

from auth.services.security_service import SecurityService
from core.cache import cache, invalidate_tags
from user.entities.user import User
from user.repositories.user_repository import UserRepository
from user.schemas.user_schema import (
    CreateUserRequest,
    UpdateUserRequest,
)


class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

    async def register(self, data: CreateUserRequest) -> User:
        password_hash = SecurityService.hash_password(data.password)
        return await self.repo.add(data.name, data.email, password_hash)

    @cache(ttl=3600, tags=["users"])
    async def get(self, user_id: UUID) -> User | None:
        return await self.repo.get(user_id)

    async def update(self, user_id: UUID, data: UpdateUserRequest) -> User | None:
        fields = data.model_dump(exclude_unset=True, exclude={"password"})
        if data.password is not None:
            fields["password_hash"] = SecurityService.hash_password(data.password)

        result = await self.repo.update(id=user_id, **fields)

        if result:
            await invalidate_tags("users")

        return result

    async def delete(
        self, user_id: UUID, force: bool = False, auto_commit: bool = True
    ) -> User | None:
        if force:
            result = await self.repo.force_delete(user_id, auto_commit=auto_commit)
        else:
            result = await self.repo.delete(user_id, auto_commit=auto_commit)

        if result and auto_commit:
            await invalidate_tags("users")

        return result
