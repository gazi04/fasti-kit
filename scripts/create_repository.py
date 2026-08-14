from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Prompt

from scripts._boilerplate import (
    parse_fields,
    to_pascal_case,
    to_snake_case,
    update_init,
    write_new_file,
)

console = Console()


def create_repository(
    domain: str = typer.Option(None, "--domain", "-d", help="Target domain folder"),
    name: str = typer.Option(None, "--name", "-n", help="Entity/Repository name"),
    fields: str = typer.Option(
        None, "--fields", "-f", help="Fields: name:str,price:float"
    ),
) -> None:
    """Scaffold a new repository interactively or via CLI flags."""

    # 1. Interactive Prompts
    if not domain:
        domain = Prompt.ask(
            "[bold blue]Enter domain name[/bold blue] (e.g., inventory)"
        )
    if not name:
        name = Prompt.ask(
            "[bold blue]Enter repository name[/bold blue] (e.g., product)"
        )
    if fields is None:
        console.print("[dim]Supported types: str, int, float, bool, uuid[/dim]")
        fields = Prompt.ask(
            "[bold blue]Enter fields[/bold blue] (e.g., title:str,price:float) or leave blank",
            default="",
        )

    # 2. Setup Variables
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)
    parsed_fields = parse_fields(fields)

    # 3. Format Field Expressions
    if parsed_fields:
        add_params = ", ".join([f"{f['name']}: {f['py_type']}" for f in parsed_fields])
        add_signature = f"self, {add_params}"
        model_kwargs = ", ".join([f"{f['name']}={f['name']}" for f in parsed_fields])
        model_instantiation = f"{pascal}Model({model_kwargs})"
        to_entity_fields = (
            "\n            ".join(
                [f"{f['name']}=model.{f['name']}," for f in parsed_fields]
            )
            + "\n            "
        )
    else:
        add_signature = "self, **fields"
        model_instantiation = f"{pascal}Model(**fields)"
        to_entity_fields = "# TODO: map domain-specific fields here (e.g. name=model.name)\n            "

    # 4. Generate Content
    layer_dir = Path(domain) / "repositories"
    file_path = layer_dir / f"{snake}_repository.py"

    template = f"""import uuid
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from {domain}.entities.{snake} import {pascal}
from {domain}.models import {pascal}Model


class {pascal}Repository:
    def __init__(self, db: AsyncSession) -> None:
        self.db: AsyncSession = db

    async def add({add_signature}) -> {pascal}:
        model = {model_instantiation}
        self.db.add(model)
        await self.db.commit()
        await self.db.refresh(model)
        return self._to_entity(model)

    async def get(self, id: UUID) -> Optional[{pascal}]:
        result = await self.db.scalar(select({pascal}Model).where({pascal}Model.id == id))

        if result is None:
            return None

        return self._to_entity(result)

    async def update(self, id: UUID, **fields) -> Optional[{pascal}]:
        record = await self.db.get({pascal}Model, id)

        if record is None:
            return None

        for key, value in fields.items():
            if value is None:
                continue

            setattr(record, key, value)

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("{pascal} update violates a uniqueness constraint")

        await self.db.refresh(record)
        return self._to_entity(record)

    async def delete(self, id: UUID) -> Optional[{pascal}]:
        record = await self.db.get({pascal}Model, id)

        if record is None:
            return None

        record.is_active = False
        await self.db.commit()
        await self.db.refresh(record)
        return self._to_entity(record)

    async def force_delete(self, id: UUID) -> Optional[{pascal}]:
        record = await self.db.get({pascal}Model, id)

        if record is None:
            return None
        result = self._to_entity(record)

        await self.db.delete(record)
        await self.db.commit()
        return result

    @staticmethod
    def _to_entity(model: {pascal}Model) -> {pascal}:
        return {pascal}(
            id=model.id,
            {to_entity_fields}is_active=model.is_active,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
"""

    # 5. Write File & Update __init__.py
    write_new_file(file_path, template)
    update_init(
        layer_dir / "__init__.py", f"{snake}_repository", [f"{pascal}Repository"]
    )

    console.print(
        f"[bold green]✨ Created repository {pascal}Repository at {file_path}[/bold green]"
    )


def main() -> None:
    typer.run(create_repository)


if __name__ == "__main__":
    main()
