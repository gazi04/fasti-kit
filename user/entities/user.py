from dataclasses import dataclass
from datetime import datetime
import uuid


@dataclass
class User:
    id: uuid.UUID
    email: str
    full_name: str
    password_hash: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
