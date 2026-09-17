from uuid import uuid4

from bcrypt import checkpw, gensalt, hashpw

from core.database import force_primary_var
from user.entities.user import User
from user.repositories.user_repository import UserRepository


class SecurityService:
    @staticmethod
    def hash_password(password: str) -> str:
        return hashpw(password.encode(), gensalt()).decode()

    @staticmethod
    def check_password(password: str, hashed_password: str) -> bool:
        return checkpw(password.encode(), hashed_password.encode())

    @staticmethod
    async def authenticate(
        email: str, password: str, user_repository: UserRepository
    ) -> User | None:
        force_primary_var.set(True)
        user = await user_repository.get_by_email(email)

        password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
        password_ok = SecurityService.check_password(password, password_hash)

        if (
            user is None
            or not password_ok
            or not user.is_active
            or not user.is_verified
        ):
            return None
        return user


# Precomputed once at import time so a login for a nonexistent/inactive/
# unverified account still pays the same bcrypt cost as a real password
# check — otherwise response timing leaks account-state to an attacker.
_DUMMY_PASSWORD_HASH = SecurityService.hash_password(uuid4().hex)
