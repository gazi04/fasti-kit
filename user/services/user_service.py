from auth.services.security_service import SecurityService
from user.entities.user import User
from user.repositories.user_repository import UserRepository
from user.schemas.user_schema import CreateUserRequest, GetUserRequest


class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

    async def register(self, data: CreateUserRequest) -> User:
        password_hash = SecurityService.hash_password(data.password)
        return await self.repo.add(data.name, data.email, password_hash)

    async def get_by_email(self, data: GetUserRequest) -> User:
        return await self.repo.get_by_email(data.email)
