from uuid import uuid4

from bcrypt import checkpw, gensalt, hashpw

from auth.services.password_hasher import password_hasher
from core.password import fits_bcrypt
from user.entities.user import User
from user.repositories.user_repository import UserRepository


def _hash(password: str) -> str:
    return hashpw(password.encode(), gensalt()).decode()


def _check(password: str, hashed_password: str) -> bool:
    return checkpw(password.encode(), hashed_password.encode())


class SecurityService:
    @staticmethod
    async def hash_password(password: str) -> str:
        return await password_hasher.run(_hash, password)

    @staticmethod
    async def check_password(password: str, hashed_password: str) -> bool:
        if not fits_bcrypt(password):
            return False
        return await password_hasher.run(_check, password, hashed_password)

    @staticmethod
    async def authenticate(
        email: str, password: str, user_repository: UserRepository
    ) -> User | None:
        user = await user_repository.get_by_email(email, consistent=True)

        password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
        password_ok = await SecurityService.check_password(password, password_hash)

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
_DUMMY_PASSWORD_HASH = _hash(uuid4().hex)
