import argparse
from pathlib import Path

from scripts._boilerplate import to_pascal_case, to_snake_case, update_init, write_new_file

TEMPLATE = '''from fastapi import APIRouter

{route_var} = APIRouter(prefix="/{prefix}", tags=["{tag}"])

# TODO: add endpoints
'''


def create_route(domain: str, name: str) -> None:
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)
    route_var = f"{snake}_router"

    layer_dir = Path(domain) / "routes"
    file_path = layer_dir / f"{route_var}.py"

    write_new_file(file_path, TEMPLATE.format(route_var=route_var, prefix=snake, tag=pascal))
    update_init(layer_dir / "__init__.py", route_var, [route_var])


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold a new route")
    parser.add_argument("domain")
    parser.add_argument("name")
    args = parser.parse_args()

    create_route(args.domain, args.name)


if __name__ == "__main__":
    main()
