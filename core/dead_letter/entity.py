import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class DeadLetterJob:
    id: uuid.UUID
    job_key: str
    function: str
    queue_name: str
    kwargs: dict[str, Any]
    status: str
    error: str | None
    attempts: int
    failed_at: datetime
    retried_at: datetime | None
