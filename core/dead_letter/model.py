import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class DeadLetterJobModel(Base):
    __tablename__ = "dead_letter_jobs"
    __table_args__ = (
        Index("ix_dead_letter_jobs_failed_at", "failed_at"),
        Index("ix_dead_letter_jobs_job_key", "job_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_key: Mapped[str] = mapped_column(String(255))
    function: Mapped[str] = mapped_column(String(255))
    queue_name: Mapped[str] = mapped_column(String(255))
    kwargs: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    retried_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
