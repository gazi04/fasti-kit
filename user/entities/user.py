import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class User:
    id: uuid.UUID
    email: str
    full_name: str
    password_hash: str
    is_active: bool
    is_verified: bool
    pending_verification_jti: str | None
    pending_password_reset_jti: str | None
    created_at: datetime
    updated_at: datetime
    scopes: str = "users:read users:write"
