import argparse
from pathlib import Path

from scripts._boilerplate import to_pascal_case, to_snake_case, update_init, write_new_file

TEMPLATE = '''from datetime import datetime
import uuid

from pydantic import BaseModel


class Create{class_name}Request(BaseModel):
    # TODO: add domain-specific fields here (e.g. name: str)
    pass


class Update{class_name}Request(BaseModel):
    # TODO: add domain-specific fields here, all Optional (e.g. from typing import Optional;
    # name: Optional[str] = None)
    pass


class Get{class_name}Request(BaseModel):
    id: uuid.UUID


class {class_name}Response(BaseModel):
    id: uuid.UUID
    # TODO: add domain-specific fields here (e.g. name: str)
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {{'from_attributes': True}}
'''


def create_schema(domain: str, name: str) -> None:
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)

    layer_dir = Path(domain) / "schemas"
    file_path = layer_dir / f"{snake}_schema.py"

    write_new_file(file_path, TEMPLATE.format(class_name=pascal))
    update_init(
        layer_dir / "__init__.py",
        f"{snake}_schema",
        [f"Create{pascal}Request", f"Update{pascal}Request", f"Get{pascal}Request", f"{pascal}Response"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold new schemas")
    parser.add_argument("domain")
    parser.add_argument("name")
    args = parser.parse_args()

    create_schema(args.domain, args.name)


if __name__ == "__main__":
    main()
