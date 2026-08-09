from tests.factories.base import BasePydanticFactory, BaseSQLAlchemyFactory
from user.models import UserModel
from user.schemas import CreateUserRequest


class UserFactory(BaseSQLAlchemyFactory[UserModel]):
    __model__ = UserModel


class CreateUserFactory(BasePydanticFactory[CreateUserRequest]):
    __model__ = CreateUserRequest
