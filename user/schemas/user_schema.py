from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr
import uuid


class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class GetUserRequest(BaseModel):
    email: str


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_verified: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
