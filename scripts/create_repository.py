import argparse
from pathlib import Path

from scripts._boilerplate import to_pascal_case, to_snake_case, update_init, write_new_file

TEMPLATE = '''from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from {domain}.entities.{snake} import {class_name}
from {domain}.models import {class_name}Model


class {class_name}Repository:
    def __init__(self, db: AsyncSession) -> None:
        self.db: AsyncSession = db

    async def add(self, **fields) -> {class_name}:
        # TODO: once domain fields exist, replace **fields with explicit kwargs, e.g.
        # async def add(self, name: str, description: str) -> {class_name}:
        model = {class_name}Model(**fields)
        self.db.add(model)
        await self.db.commit()
        await self.db.refresh(model)
        return self._to_entity(model)

    async def get(self, id: UUID) -> Optional[{class_name}]:
        result = await self.db.scalar(select({class_name}Model).where({class_name}Model.id == id))

        if result is None:
            return

        return self._to_entity(result)

    async def update(self, id: UUID, **fields) -> Optional[{class_name}]:
        record = await self.db.get({class_name}Model, id)

        if record is None:
            return

        for key, value in fields.items():
            if value is None:
                continue

            setattr(record, key, value)

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("{class_name} update violates a uniqueness constraint")

        await self.db.refresh(record)
        return self._to_entity(record)

    async def delete(self, id: UUID) -> Optional[{class_name}]:
        record = await self.db.get({class_name}Model, id)

        if record is None:
            return

        record.is_active = False
        await self.db.commit()
        await self.db.refresh(record)
        return self._to_entity(record)

    async def force_delete(self, id: UUID) -> Optional[{class_name}]:
        record = await self.db.get({class_name}Model, id)

        if record is None:
            return
        result = self._to_entity(record)

        await self.db.delete(record)
        await self.db.commit()
        return result

    @staticmethod
    def _to_entity(model: {class_name}Model) -> {class_name}:
        return {class_name}(
            id=model.id,
            # TODO: map domain-specific fields here (e.g. name=model.name)
            is_active=model.is_active,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
'''


def create_repository(domain: str, name: str) -> None:
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)

    layer_dir = Path(domain) / "repositories"
    file_path = layer_dir / f"{snake}_repository.py"

    write_new_file(file_path, TEMPLATE.format(class_name=pascal, domain=domain, snake=snake))
    update_init(layer_dir / "__init__.py", f"{snake}_repository", [f"{pascal}Repository"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold a new repository")
    parser.add_argument("domain")
    parser.add_argument("name")
    args = parser.parse_args()

    create_repository(args.domain, args.name)


if __name__ == "__main__":
    main()
