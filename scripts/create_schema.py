import argparse
from pathlib import Path

from scripts._boilerplate import to_pascal_case, to_snake_case, update_init, write_new_file

TEMPLATE = '''from pydantic import BaseModel


class {class_name}Create(BaseModel):
    # TODO: add fields
    pass


class {class_name}Read(BaseModel):
    # TODO: add fields
    pass
'''


def create_schema(domain: str, name: str) -> None:
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)

    layer_dir = Path(domain) / "schemas"
    file_path = layer_dir / f"{snake}_schema.py"

    write_new_file(file_path, TEMPLATE.format(class_name=pascal))
    update_init(layer_dir / "__init__.py", f"{snake}_schema", [f"{pascal}Create", f"{pascal}Read"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold new schemas")
    parser.add_argument("domain")
    parser.add_argument("name")
    args = parser.parse_args()

    create_schema(args.domain, args.name)


if __name__ == "__main__":
    main()
