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
        add_signature = f"self, {add_params}, auto_commit: bool = True"
        model_kwargs = ", ".join([f"{f['name']}={f['name']}" for f in parsed_fields])
        model_instantiation = f"{pascal}Model({model_kwargs})"
        to_entity_fields = (
            "\n            ".join(
                [f"{f['name']}=model.{f['name']}," for f in parsed_fields]
            )
            + "\n            "
        )
    else:
        add_signature = "self, auto_commit: bool = True, **fields"
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

from core.database import force_primary_var
from {domain}.entities.{snake} import {pascal}
from {domain}.models import {pascal}Model


class {pascal}Repository:
    def __init__(self, db: AsyncSession) -> None:
        self.db: AsyncSession = db

    async def add({add_signature}) -> {pascal}:
        force_primary_var.set(True)
        model = {model_instantiation}

        await self._flush_or_raise(model)

        if auto_commit:
            await self.db.commit()
            await self.db.refresh(model)

        return self._to_entity(model)

    async def get(self, id: UUID) -> Optional[{pascal}]:
        result = await self.db.scalar(select({pascal}Model).where({pascal}Model.id == id))

        if result is None:
            return None

        return self._to_entity(result)

    async def update(
        self, id: UUID, auto_commit: bool = True, **fields
    ) -> Optional[{pascal}]:
        force_primary_var.set(True)
        record = await self.db.get({pascal}Model, id)

        if record is None:
            return None

        for key, value in fields.items():
            setattr(record, key, value)

        if auto_commit:
            await self._flush_or_raise()
            await self.db.commit()
            await self.db.refresh(record)
        else:
            await self._flush_or_raise()

        return self._to_entity(record)

    async def delete(self, id: UUID, auto_commit: bool = True) -> Optional[{pascal}]:
        force_primary_var.set(True)
        record = await self.db.get({pascal}Model, id)

        if record is None:
            return None

        record.is_active = False

        if auto_commit:
            await self.db.commit()
            await self.db.refresh(record)
        else:
            await self.db.flush()

        return self._to_entity(record)

    async def force_delete(
        self, id: UUID, auto_commit: bool = True
    ) -> Optional[{pascal}]:
        force_primary_var.set(True)
        record = await self.db.get({pascal}Model, id)

        if record is None:
            return None
        result = self._to_entity(record)

        await self.db.delete(record)

        if auto_commit:
            await self.db.commit()
        else:
            await self.db.flush()

        return result

    async def _flush_or_raise(self, model: Optional[{pascal}Model] = None) -> None:
        \"\"\"Flush inside a SAVEPOINT so a constraint violation stays contained.

        `model` is added *inside* the savepoint on purpose — adding it beforehand
        would put it in the outer SessionTransaction, so a flush failure inside
        the savepoint would deactivate the outer transaction too (PendingRollbackError
        on every later statement), defeating the point of the savepoint.
        \"\"\"
        try:
            async with self.db.begin_nested():
                if model is not None:
                    self.db.add(model)
                await self.db.flush()
        except IntegrityError as err:
            # TODO: inspect err.orig for the violated column and raise a
            # field-specific ValueError once you know your unique constraints.
            raise ValueError("{pascal} violates a uniqueness constraint") from err

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
