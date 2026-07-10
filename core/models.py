"""
This file acts as a "Manifest" for SQLAlchemy.
And can be used in the case where we want to import all the models but at the same time keep a clean code.
"""

from core.database import Base  # noqa: F401
from user.models import UserModel
from auth.models import RevokedTokenModel
