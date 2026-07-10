from dataclasses import dataclass
from datetime import datetime
import uuid


@dataclass
class RevokedToken:
    id: uuid.UUID
    jti: str
    expires_at: datetime
