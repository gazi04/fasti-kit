from pathlib import Path

import typer

from scripts._boilerplate import (
    ask_domain,
    ask_fields,
    ask_name,
    cli_errors,
    console,
    format_paths,
    parse_fields,
    require_domain,
    resolve_names,
    update_init,
    write_new_file,
)


def generate_repository(domain: str, name: str, fields: str = "") -> list[Path]:
    snake, pascal = resolve_names(domain, name)
    parsed_fields = parse_fields(fields)

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

    uuid_import = (
        "import uuid\n" if any(f["type"] == "uuid" for f in parsed_fields) else ""
    )

    layer_dir = Path(domain) / "repositories"
    file_path = layer_dir / f"{snake}_repository.py"

    template = f"""{uuid_import}from uuid import UUID

from fastapi_pagination.cursor import CursorPage, CursorParams
from fastapi_pagination.ext.sqlalchemy import apaginate
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

    async def get(self, id: UUID) -> {pascal} | None:
        result = await self.db.scalar(select({pascal}Model).where({pascal}Model.id == id))

        if result is None:
            return None

        return self._to_entity(result)

    async def update(
        self, id: UUID, auto_commit: bool = True, **fields
    ) -> {pascal} | None:
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

    async def delete(self, id: UUID, auto_commit: bool = True) -> {pascal} | None:
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
    ) -> {pascal} | None:
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

    async def list(self, params: CursorParams | None = None) -> CursorPage[{pascal}]:
        return await apaginate(
            self.db,
            select({pascal}Model).order_by(
                {pascal}Model.created_at.desc(), {pascal}Model.id.desc()
            ),
            params=params or CursorParams(),
            transformer=lambda models: [self._to_entity(model) for model in models],
        )

    async def _flush_or_raise(self, model: {pascal}Model | None = None) -> None:
        \"\"\"Flush inside a SAVEPOINT so a constraint violation stays contained.

        `model` is added *inside* the savepoint on purpose. Adding it beforehand
        would put it in the outer SessionTransaction, so a flush failure inside
        the savepoint would deactivate the outer transaction too
        (PendingRollbackError on every later statement).
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

    write_new_file(file_path, template)
    init = update_init(
        layer_dir / "__init__.py", f"{snake}_repository", [f"{pascal}Repository"]
    )
    return [file_path, init]


def create_repository(
    domain: str | None = typer.Option(
        None, "--domain", "-d", help="Target domain folder"
    ),
    name: str | None = typer.Option(
        None, "--name", "-n", help="Entity/Repository name"
    ),
    fields: str | None = typer.Option(
        None, "--fields", "-f", help="Fields: name:str,price:float"
    ),
) -> None:
    """Scaffold a new repository interactively or via CLI flags."""
    domain = ask_domain(domain)
    name = ask_name(name, "repository")
    fields = ask_fields(fields)

    with cli_errors():
        require_domain(domain)
        paths = generate_repository(domain, name, fields)

    format_paths(paths)
    console.print(
        f"[bold green]✨ Repository for {name} is ready in {domain}/repositories[/bold green]"
    )


def main() -> None:
    typer.run(create_repository)


if __name__ == "__main__":
    main()
