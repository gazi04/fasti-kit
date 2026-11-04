"""drop default user scopes

Revision ID: d223a0cb723d
Revises: 80f27a9e6fcd
Create Date: 2026-11-02 21:05:12.763981

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d223a0cb723d"
down_revision: Union[str, Sequence[str], None] = "80f27a9e6fcd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_SCOPES = "users:read users:write"


def _remove_scopes(*scopes: str) -> None:
    op.execute(
        sa.text(
            "UPDATE users SET scopes = array_to_string(ARRAY("
            "SELECT s FROM unnest(string_to_array(scopes, ' ')) AS s "
            "WHERE s <> '' AND s <> ALL(:scopes)), ' ')"
        ).bindparams(scopes=list(scopes))
    )


def upgrade() -> None:
    _remove_scopes("users:read", "users:write")
    op.execute(
        "UPDATE users SET scopes = trim(scopes || ' admin:write') "
        "WHERE 'admin:read' = ANY(string_to_array(scopes, ' ')) "
        "AND NOT 'admin:write' = ANY(string_to_array(scopes, ' '))"
    )
    op.alter_column("users", "scopes", server_default="")


def downgrade() -> None:
    _remove_scopes("admin:write")
    op.execute(
        sa.text(
            "UPDATE users SET scopes = trim(:defaults || ' ' || scopes)"
        ).bindparams(defaults=DEFAULT_SCOPES)
    )
    op.alter_column("users", "scopes", server_default=DEFAULT_SCOPES)
