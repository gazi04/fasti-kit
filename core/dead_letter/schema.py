import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DeadLetterJobResponse(BaseModel):
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

    model_config = {"from_attributes": True}


class PurgeRequest(BaseModel):
    before: datetime | None = None
    only_retried: bool = True
