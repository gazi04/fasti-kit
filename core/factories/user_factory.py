import uuid

from polyfactory import Ignore

from core.factories.base import BasePydanticFactory, BaseSQLAlchemyFactory
from user.models import UserModel
from user.schemas import CreateUserRequest, UpdateUserRequest


def make_email() -> str:
    """Unique address in the `test_<hex>@example.com` shape the suite has always used."""
    return f"test_{uuid.uuid4().hex[:8]}@example.com"


class CreateUserRequestFactory(BasePydanticFactory[CreateUserRequest]):
    __model__ = CreateUserRequest
    __use_defaults__ = True

    @classmethod
    def email(cls) -> str:
        return make_email()


class UpdateUserRequestFactory(BasePydanticFactory[UpdateUserRequest]):
    __model__ = UpdateUserRequest
    __use_defaults__ = True

    @classmethod
    def email(cls) -> str:
        return make_email()


class UserModelFactory(BaseSQLAlchemyFactory[UserModel]):
    """A verified-nothing, active user. `__use_defaults__` does not reach
    SQLAlchemy column defaults, so the stable ones are pinned here and the
    server-assigned ones are left for the column default to fill on flush."""

    __model__ = UserModel

    id = Ignore()
    created_at = Ignore()
    updated_at = Ignore()
    is_active = True
    is_verified = False
    scopes = "users:read users:write"
    pending_verification_jti = None
    pending_password_reset_jti = None

    @classmethod
    def email(cls) -> str:
        return make_email()
