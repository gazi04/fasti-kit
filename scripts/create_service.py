import argparse
from pathlib import Path

from scripts._boilerplate import to_pascal_case, to_snake_case, update_init, write_new_file

TEMPLATE = '''class {class_name}Service:
    def __init__(self, repo) -> None:
        self.repo = repo

    # TODO: add methods
'''


def create_service(domain: str, name: str) -> None:
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)

    layer_dir = Path(domain) / "services"
    file_path = layer_dir / f"{snake}_service.py"

    write_new_file(file_path, TEMPLATE.format(class_name=pascal))
    update_init(layer_dir / "__init__.py", f"{snake}_service", [f"{pascal}Service"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold a new service")
    parser.add_argument("domain")
    parser.add_argument("name")
    args = parser.parse_args()

    create_service(args.domain, args.name)


if __name__ == "__main__":
    main()
