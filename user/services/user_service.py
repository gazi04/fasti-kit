from uuid import UUID, uuid4

from fastapi_pagination.cursor import CursorPage, CursorParams

from auth.services.email_verification_service import EmailVerificationService
from auth.services.security_service import SecurityService
from core.exception import EntityNotFoundError
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
        user_id = uuid4()
        token, jti = EmailVerificationService.create_verification_token(str(user_id))

        return await self.repo.register(
            id=user_id,
            full_name=data.name,
            email=data.email,
            password_hash=SecurityService.hash_password(data.password),
            pending_verification_jti=jti,
            email_payload=EmailVerificationService.build_email_payload(
                data.email, token
            ),
        )

    async def list(self, params: CursorParams | None = None) -> CursorPage[User]:
        return await self.repo.list(params)

    async def update(self, user_id: UUID, data: UpdateUserRequest) -> User:
        fields = data.model_dump(exclude_unset=True, exclude={"password"})
        if data.password is not None:
            fields["password_hash"] = SecurityService.hash_password(data.password)

        result = await self.repo.update(id=user_id, **fields)

        if result is None:
            raise EntityNotFoundError("User", str(user_id))

        return result
