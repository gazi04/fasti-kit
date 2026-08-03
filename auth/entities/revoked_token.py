import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class RevokedToken:
    id: uuid.UUID
    jti: str
    expires_at: datetime
