import uuid

from pydantic import BaseModel


class UserCreate(BaseModel):
    email: str
    password: str

class UserRead(BaseModel):
    id: uuid.UUID
    email: str
