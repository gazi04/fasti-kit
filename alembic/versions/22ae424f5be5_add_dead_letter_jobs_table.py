"""add dead_letter_jobs table

Revision ID: 22ae424f5be5
Revises: b7f3a9c1d2e4
Create Date: 2026-08-31 11:47:46.874538

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '22ae424f5be5'
down_revision: Union[str, Sequence[str], None] = 'b7f3a9c1d2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "dead_letter_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_key", sa.String(length=255), nullable=False),
        sa.Column("function", sa.String(length=255), nullable=False),
        sa.Column("queue_name", sa.String(length=255), nullable=False),
        sa.Column("kwargs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retried_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dead_letter_jobs_failed_at", "dead_letter_jobs", ["failed_at"]
    )
    op.create_index(
        "ix_dead_letter_jobs_job_key", "dead_letter_jobs", ["job_key"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_dead_letter_jobs_job_key", table_name="dead_letter_jobs")
    op.drop_index("ix_dead_letter_jobs_failed_at", table_name="dead_letter_jobs")
    op.drop_table("dead_letter_jobs")
