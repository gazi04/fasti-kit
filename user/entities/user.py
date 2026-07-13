from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import uuid


@dataclass
class User:
    id: uuid.UUID
    email: str
    full_name: str
    password_hash: str
    is_active: bool
    is_verified: bool
    pending_verification_jti: Optional[str]
    created_at: datetime
    updated_at: datetime
