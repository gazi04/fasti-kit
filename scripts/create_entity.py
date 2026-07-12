import argparse
from pathlib import Path

from scripts._boilerplate import (
    to_pascal_case,
    to_snake_case,
    update_init,
    write_new_file,
)

TEMPLATE = """from dataclasses import dataclass
from datetime import datetime
import uuid


@dataclass
class {class_name}:
    id: uuid.UUID
    # TODO: add domain-specific fields here (e.g. name: str, description: str)
    is_active: bool
    created_at: datetime
    updated_at: datetime
"""


def create_entity(domain: str, name: str) -> None:
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)

    layer_dir = Path(domain) / "entities"
    file_path = layer_dir / f"{snake}.py"

    write_new_file(file_path, TEMPLATE.format(class_name=pascal))
    update_init(layer_dir / "__init__.py", snake, [pascal])


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold a new entity")
    parser.add_argument("domain")
    parser.add_argument("name")
    args = parser.parse_args()

    create_entity(args.domain, args.name)


if __name__ == "__main__":
    main()
