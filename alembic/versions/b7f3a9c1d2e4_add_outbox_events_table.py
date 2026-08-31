"""add outbox_events table

Revision ID: b7f3a9c1d2e4
Revises: f0589143e900
Create Date: 2026-08-30 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b7f3a9c1d2e4"
down_revision: Union[str, Sequence[str], None] = "f0589143e900"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outbox_undispatched",
        "outbox_events",
        ["created_at"],
        postgresql_where=sa.text("dispatched_at IS NULL AND failed_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_outbox_undispatched", table_name="outbox_events")
    op.drop_table("outbox_events")
