import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RefreshSession:
    id: uuid.UUID
    user_id: uuid.UUID
    generation: int
    expires_at: datetime
    rotated_at: datetime | None
    revoked_at: datetime | None
