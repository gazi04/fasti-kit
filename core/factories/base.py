from typing import TypeVar

from polyfactory.factories.pydantic_factory import ModelFactory as PydanticBaseFactory
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from pydantic import BaseModel

from core.database import Base

PydanticModelT = TypeVar("PydanticModelT", bound=BaseModel)

SQLAlchemyModelT = TypeVar("SQLAlchemyModelT", bound=Base)


class BasePydanticFactory(PydanticBaseFactory[PydanticModelT]):
    __is_base_factory__ = True


class BaseSQLAlchemyFactory(SQLAlchemyFactory[SQLAlchemyModelT]):
    __is_base_factory__ = True
    __set_relationships__ = True
