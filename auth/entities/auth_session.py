import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class TokenRef:
    jti: str
    expires_at: datetime


@dataclass(frozen=True)
class AuthSession:
    user_id: uuid.UUID
    tokens: list[TokenRef] = field(default_factory=list)
    refresh_session_id: uuid.UUID | None = None
