import argparse
from pathlib import Path

from scripts._boilerplate import to_pascal_case, to_snake_case, update_init, write_new_file

TEMPLATE = '''from core.database import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

import uuid


class {class_name}Model(Base):
    __tablename__ = "{table_name}"  # TODO: pluralize table name

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # TODO: add columns
'''


def create_model(domain: str, name: str) -> None:
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)

    layer_dir = Path(domain) / "models"
    file_path = layer_dir / f"{snake}_model.py"

    write_new_file(file_path, TEMPLATE.format(class_name=pascal, table_name=snake))
    update_init(layer_dir / "__init__.py", f"{snake}_model", [f"{pascal}Model"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold a new ORM model")
    parser.add_argument("domain")
    parser.add_argument("name")
    args = parser.parse_args()

    create_model(args.domain, args.name)


if __name__ == "__main__":
    main()
