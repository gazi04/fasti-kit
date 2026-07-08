from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import uuid

@dataclass
class User:
    id: Optional[uuid.UUID]
    email: Optional[str]
    full_name: Optional[str]
    password_hash: Optional[str]
    is_active: Optional[bool]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
