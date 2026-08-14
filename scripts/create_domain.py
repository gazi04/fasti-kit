import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from scripts._boilerplate import (
    to_pascal_case,
    to_snake_case,
    write_new_file,
)

app = typer.Typer(help="Interactive DDD Scaffold Generator for fasti-kit")
console = Console()

TYPE_MAPPING = {
    "str": {"py": "str", "sqla": "String", "pydantic": "str"},
    "int": {"py": "int", "sqla": "Integer", "pydantic": "int"},
    "float": {"py": "float", "sqla": "Float", "pydantic": "float"},
    "bool": {"py": "bool", "sqla": "Boolean", "pydantic": "bool"},
    "uuid": {"py": "uuid.UUID", "sqla": "UUID(as_uuid=True)", "pydantic": "uuid.UUID"},
}


def parse_fields(fields_str: str) -> List[Dict[str, Any]]:
    """Parses 'name:str,price:float,is_active:bool=True' into structured data."""
    parsed = []
    if not fields_str:
        return parsed

    for item in fields_str.split(","):
        item = item.strip()
        if not item:
            continue

        default_val = None
        if "=" in item:
            item, default_val = item.split("=", 1)

        name, field_type = item.split(":")
        name = name.strip()

        # Skip base fields to prevent duplicate initialization
        if name in ["id", "created_at", "updated_at"]:
            continue

        parsed.append(
            {
                "name": name,
                "type": field_type.strip(),
                "default": default_val.strip() if default_val else None,
                "py_type": TYPE_MAPPING.get(field_type.strip(), TYPE_MAPPING["str"])[
                    "py"
                ],
                "sqla_type": TYPE_MAPPING.get(field_type.strip(), TYPE_MAPPING["str"])[
                    "sqla"
                ],
            }
        )
    return parsed


def auto_register_router(domain: str, snake: str, pascal: str) -> None:
    """Injects the new router into core/api_versions.py grouping imports and includes."""
    api_versions = Path("core/api_versions.py")
    if not api_versions.exists():
        console.print(
            "[yellow]⚠️ core/api_versions.py not found. Skipping auto-registration.[/yellow]"
        )
        return

    content = api_versions.read_text().split("\n")
    import_stmt = f"from {domain}.routes.{snake}_route import {snake}_router"
    include_stmt = f"v1_router.include_router({snake}_router)"

    # Check if already present
    if any(import_stmt in line for line in content) and any(
        include_stmt in line for line in content
    ):
        return

    # 1. Insert the import statement directly above 'API_V1_PREFIX = "/api/v1"'
    for i, line in enumerate(content):
        if line.startswith("API_V1_PREFIX"):
            content.insert(i, import_stmt)
            break

    # 2. Insert the include statement right after the last 'v1_router.include_router'
    last_include_idx = -1
    for i, line in enumerate(content):
        if line.startswith("v1_router.include_router"):
            last_include_idx = i

    if last_include_idx != -1:
        content.insert(last_include_idx + 1, include_stmt)
    else:
        content.append(include_stmt)

    api_versions.write_text("\n".join(content))
    console.print(
        f"[green]✔ Auto-registered {snake}_router neatly in core/api_versions.py[/green]"
    )


@app.command(name="generate")
def create_domain(
    domain: str = typer.Option(
        None, "--domain", "-d", help="Target domain folder (e.g., inventory)"
    ),
    name: str = typer.Option(None, "--name", "-n", help="Entity name (e.g., product)"),
    fields: str = typer.Option(
        None, "--fields", "-f", help="Fields: name:str,price:float"
    ),
):
    """Generates a complete DDD slice."""
    if not domain:
        domain = Prompt.ask(
            "[bold blue]Enter domain name[/bold blue] (e.g., inventory)"
        )
    if not name:
        name = Prompt.ask("[bold blue]Enter entity name[/bold blue] (e.g., product)")
    if not fields:
        console.print("[dim]Supported types: str, int, float, bool, uuid[/dim]")
        fields = Prompt.ask(
            "[bold blue]Enter fields[/bold blue] (e.g., title:str,price:float,is_active:bool=True)"
        )

    snake = to_snake_case(name)
    pascal = to_pascal_case(name)
    parsed_fields = parse_fields(fields)

    table = Table(title=f"Generating {pascal} in '{domain}' domain")
    table.add_column("Field", style="cyan")
    table.add_column("Type (Python)", style="magenta")
    table.add_column("Type (SQLAlchemy)", style="green")
    table.add_column("Default", style="yellow")

    for f in parsed_fields:
        table.add_row(
            f["name"],
            f["py_type"],
            f["sqla_type"],
            str(f["default"]) if f["default"] else "None",
        )
    console.print(table)

    entity_fields = "\n    ".join(
        [f"{f['name']}: {f['py_type']}" for f in parsed_fields]
    )
    model_fields = "\n    ".join(
        [
            f"{f['name']}: Mapped[{f['py_type']}] = mapped_column({f['sqla_type']}{', default=' + f['default'] if f['default'] else ''})"
            for f in parsed_fields
        ]
    )
    schema_fields = "\n    ".join(
        [f"{f['name']}: {f['py_type']}" for f in parsed_fields]
    )
    repo_add_args = ", ".join([f"{f['name']}: {f['py_type']}" for f in parsed_fields])
    repo_add_kwargs = ", ".join([f"{f['name']}={f['name']}" for f in parsed_fields])
    to_entity_kwargs = ",\n            ".join(
        [f"{f['name']}=model.{f['name']}" for f in parsed_fields]
    )

    templates = {
        f"entities/{snake}.py": f"""import uuid
from dataclasses import dataclass
from datetime import datetime

@dataclass
class {pascal}:
    id: uuid.UUID
    {entity_fields}
    created_at: datetime
    updated_at: datetime
""",
        f"models/{snake}_model.py": f"""import uuid
from datetime import UTC, datetime
from sqlalchemy import Boolean, DateTime, String, Integer, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base

class {pascal}Model(Base):
    __tablename__ = "{snake}s"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    {model_fields}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
""",
        f"schemas/{snake}_schema.py": f"""import uuid
from datetime import datetime
from pydantic import BaseModel

class Create{pascal}Request(BaseModel):
    {schema_fields}

class Update{pascal}Request(BaseModel):
    {schema_fields} # TODO: Make fields Optional

class {pascal}Response(BaseModel):
    id: uuid.UUID
    {schema_fields}
    created_at: datetime
    updated_at: datetime

    model_config = {{"from_attributes": True}}
""",
        f"repositories/{snake}_repository.py": f"""import uuid
from uuid import UUID
from fastapi_pagination.cursor import CursorPage, CursorParams
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy import select
from sqlalchemy.ext.asyncio.session import AsyncSession
from {domain}.entities.{snake} import {pascal}
from {domain}.models.{snake}_model import {pascal}Model

class {pascal}Repository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, {repo_add_args}) -> {pascal}:
        model = {pascal}Model({repo_add_kwargs})
        self.db.add(model)
        await self.db.commit()
        await self.db.refresh(model)
        return self._to_entity(model)

    async def get(self, id: UUID) -> {pascal} | None:
        result = await self.db.scalar(select({pascal}Model).where({pascal}Model.id == id))
        return self._to_entity(result) if result else None

    async def update(self, id: UUID, **fields) -> {pascal} | None:
        record = await self.db.get({pascal}Model, id)
        if not record:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(record, key, value)
        await self.db.commit()
        await self.db.refresh(record)
        return self._to_entity(record)

    async def delete(self, id: UUID) -> {pascal} | None:
        record = await self.db.get({pascal}Model, id)
        if not record:
            return None
        await self.db.delete(record)
        await self.db.commit()
        return self._to_entity(record)

    async def list(self, params: CursorParams | None = None) -> CursorPage[{pascal}]:
        return await apaginate(
            self.db,
            select({pascal}Model).order_by({pascal}Model.created_at.desc(), {pascal}Model.id.desc()),
            params=params or CursorParams(),
            transformer=lambda models: [self._to_entity(model) for model in models],
        )

    @staticmethod
    def _to_entity(model: {pascal}Model) -> {pascal}:
        return {pascal}(
            id=model.id,
            {to_entity_kwargs},
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
""",
        f"services/{snake}_service.py": f"""from uuid import UUID
from {domain}.entities.{snake} import {pascal}
from {domain}.repositories.{snake}_repository import {pascal}Repository
from {domain}.schemas.{snake}_schema import Create{pascal}Request, Update{pascal}Request

class {pascal}Service:
    def __init__(self, repo: {pascal}Repository) -> None:
        self.repo = repo

    async def create(self, data: Create{pascal}Request) -> {pascal}:
        return await self.repo.add(**data.model_dump())

    async def get(self, id: UUID) -> {pascal} | None:
        return await self.repo.get(id)

    async def update(self, id: UUID, data: Update{pascal}Request) -> {pascal} | None:
        return await self.repo.update(id=id, **data.model_dump(exclude_unset=True))

    async def delete(self, id: UUID) -> {pascal} | None:
        return await self.repo.delete(id)
""",
        f"routes/{snake}_route.py": f"""from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi_pagination.cursor import CursorPage, CursorParams
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db

from {domain}.repositories.{snake}_repository import {pascal}Repository
from {domain}.schemas.{snake}_schema import Create{pascal}Request, Update{pascal}Request, {pascal}Response
from {domain}.services.{snake}_service import {pascal}Service

{snake}_router = APIRouter(prefix="/{snake.replace("_", "-")}", tags=["{pascal}"])

def get_{snake}_service(db: AsyncSession = Depends(get_db)) -> {pascal}Service:
    return {pascal}Service({pascal}Repository(db))

@{snake}_router.post("/create", response_model={pascal}Response)
async def create_{snake}(data: Create{pascal}Request, service: {pascal}Service = Depends(get_{snake}_service)):
    return await service.create(data)

@{snake}_router.get("/get/{{id}}", response_model={pascal}Response)
async def get_{snake}(id: UUID, service: {pascal}Service = Depends(get_{snake}_service)):
    record = await service.get(id)
    if not record:
        raise HTTPException(404, "{pascal} not found")
    return record

@{snake}_router.patch("/update/{{id}}", response_model={pascal}Response)
async def update_{snake}(id: UUID, data: Update{pascal}Request, service: {pascal}Service = Depends(get_{snake}_service)):
    record = await service.update(id, data)
    if not record:
        raise HTTPException(404, "{pascal} not found")
    return record

@{snake}_router.delete("/delete/{{id}}")
async def delete_{snake}(id: UUID, service: {pascal}Service = Depends(get_{snake}_service)):
    deleted = await service.delete(id)
    if not deleted:
        raise HTTPException(404, "{pascal} not found")
    return {{"message": "{pascal} deleted"}}

@{snake}_router.get("/list", response_model=CursorPage[{pascal}Response])
async def list_{snake}s(params: CursorParams = Depends(), db: AsyncSession = Depends(get_db)):
    repo = {pascal}Repository(db)
    return await repo.list(params)
""",
    }

    # Write files securely
    domain_path = Path(domain)
    for folder in [
        "entities",
        "models",
        "schemas",
        "repositories",
        "services",
        "routes",
    ]:
        folder_path = domain_path / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        # Fix for __init__.py syntax errors: simply touch an empty file
        (folder_path / "__init__.py").touch()

    with console.status(f"[bold green]Generating {pascal} DDD layers..."):
        for rel_path, content in templates.items():
            file_path = domain_path / rel_path
            write_new_file(file_path, content)
            console.print(f"  [cyan]Created:[/cyan] {file_path}")

    auto_register_router(domain, snake, pascal)
    console.print(
        f"\n[bold green]✨ Successfully generated {pascal} CRUD in {domain}/![/bold green]"
    )


if __name__ == "__main__":
    app()
