import argparse
from pathlib import Path

from scripts._boilerplate import to_pascal_case, to_snake_case, update_init, write_new_file

TEMPLATE = '''from typing import Optional
from uuid import UUID

from {domain}.entities.{snake} import {class_name}
from {domain}.repositories.{snake}_repository import {class_name}Repository
from {domain}.schemas.{snake}_schema import Create{class_name}Request, Update{class_name}Request


class {class_name}Service:
    def __init__(self, repo: {class_name}Repository) -> None:
        self.repo = repo

    async def create(self, data: Create{class_name}Request) -> {class_name}:
        return await self.repo.add(**data.model_dump())

    async def get(self, id: UUID) -> Optional[{class_name}]:
        return await self.repo.get(id)

    async def update(self, id: UUID, data: Update{class_name}Request) -> Optional[{class_name}]:
        return await self.repo.update(id=id, **data.model_dump(exclude_unset=True))

    async def delete(self, id: UUID, force: bool = False) -> Optional[{class_name}]:
        if force:
            return await self.repo.force_delete(id)

        return await self.repo.delete(id)
'''


def create_service(domain: str, name: str) -> None:
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)

    layer_dir = Path(domain) / "services"
    file_path = layer_dir / f"{snake}_service.py"

    write_new_file(file_path, TEMPLATE.format(class_name=pascal, domain=domain, snake=snake))
    update_init(layer_dir / "__init__.py", f"{snake}_service", [f"{pascal}Service"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold a new service")
    parser.add_argument("domain")
    parser.add_argument("name")
    args = parser.parse_args()

    create_service(args.domain, args.name)


if __name__ == "__main__":
    main()
