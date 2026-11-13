import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from core.password import NewPassword


class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    password: NewPassword


class UpdateUserRequest(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    password: NewPassword | None = None


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_verified: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
