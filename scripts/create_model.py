import argparse
from pathlib import Path

from scripts._boilerplate import (
    pluralize,
    to_pascal_case,
    to_snake_case,
    update_init,
    write_new_file,
)

TEMPLATE = """from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base

import uuid


class {class_name}Model(Base):
    __tablename__ = "{table_name}"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # TODO: add domain-specific columns here (e.g. name: Mapped[str] = mapped_column(String(255)))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
"""


def create_model(domain: str, name: str) -> None:
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)
    table_name = pluralize(snake)

    layer_dir = Path(domain) / "models"
    file_path = layer_dir / f"{snake}_model.py"

    write_new_file(file_path, TEMPLATE.format(class_name=pascal, table_name=table_name))
    update_init(layer_dir / "__init__.py", f"{snake}_model", [f"{pascal}Model"])

    print(
        f"reminder: register the new model for Alembic/metadata discovery - add this line "
        f"to core/models.py:\n    from {domain}.models import {pascal}Model"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold a new ORM model")
    parser.add_argument("domain")
    parser.add_argument("name")
    args = parser.parse_args()

    create_model(args.domain, args.name)


if __name__ == "__main__":
    main()
