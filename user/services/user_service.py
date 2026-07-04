from user.entities.user import User
from user.repositories.user_repository import UserRepository
from user.schemas.user_schema import UserCreate


class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

    async def register(self, data: UserCreate) -> User:
        password_hash = data.password
        return await self.repo.add(data.email, password_hash)
