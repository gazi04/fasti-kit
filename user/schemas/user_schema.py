from datetime import datetime
from pydantic import BaseModel
import uuid



class CreateUserRequest(BaseModel):
    name: str
    email: str
    password: str

class GetUserRequest(BaseModel):
    email: str

class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {'from_attributes': True}
