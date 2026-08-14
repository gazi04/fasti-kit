from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Prompt

from scripts._boilerplate import (
    to_pascal_case,
    to_snake_case,
    update_init,
    write_new_file,
)

console = Console()


def create_route(
    domain: str = typer.Option(None, "--domain", "-d", help="Target domain folder"),
    name: str = typer.Option(None, "--name", "-n", help="Entity/Route name"),
    fields: str = typer.Option(None, "--fields", "-f", help="Ignored for routes, kept for CLI consistency"),
) -> None:
    """Scaffold a new route interactively or via CLI flags."""

    # 1. Interactive Prompts
    if not domain:
        domain = Prompt.ask("[bold blue]Enter domain name[/bold blue] (e.g., inventory)")
    if not name:
        name = Prompt.ask("[bold blue]Enter route name[/bold blue] (e.g., product)")

    # 2. Setup Variables
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)
    route_var = f"{snake}_router"
    prefix = snake.replace("_", "-")  # Standard REST practice (e.g. order-item instead of order_item)

    # 3. Generate Content
    layer_dir = Path(domain) / "routes"
    file_path = layer_dir / f"{route_var}.py"

    template = f"""from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from {domain}.entities.{snake} import {pascal}
from {domain}.repositories.{snake}_repository import {pascal}Repository
from {domain}.schemas.{snake}_schema import Create{pascal}Request, Update{pascal}Request, {pascal}Response
from {domain}.services.{snake}_service import {pascal}Service

# Uncomment to require an authenticated caller (see auth/dependencies.py):
# from authx import TokenPayload
# from auth.dependencies import auth

{route_var} = APIRouter(prefix="/{prefix}", tags=["{pascal}"])


@{route_var}.post("/create", response_model={pascal}Response)
async def create_{snake}(data: Create{pascal}Request, db: AsyncSession = Depends(get_db)) -> {pascal}:
    service = {pascal}Service({pascal}Repository(db))
    return await service.create(data)


@{route_var}.get("/get/{{id}}", response_model={pascal}Response)
async def get_{snake}(id: UUID, db: AsyncSession = Depends(get_db)) -> Optional[{pascal}]:
    service = {pascal}Service({pascal}Repository(db))
    record = await service.get(id)

    if record is None:
        raise HTTPException(404, "{pascal} not found")

    return record


@{route_var}.patch("/update/{{id}}", response_model={pascal}Response)
async def update_{snake}(
    id: UUID,
    data: Update{pascal}Request,
    db: AsyncSession = Depends(get_db),
    # payload: TokenPayload = Depends(auth.token_required(type='access', locations=['headers'])),
) -> Optional[{pascal}]:
    service = {pascal}Service({pascal}Repository(db))

    try:
        record = await service.update(id, data)
    except ValueError as exc:
        raise HTTPException(409, str(exc))

    if record is None:
        raise HTTPException(404, "{pascal} not found")

    return record


@{route_var}.delete("/delete/{{id}}")
async def delete_{snake}(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    # payload: TokenPayload = Depends(auth.token_required(type='access', locations=['headers'])),
):
    service = {pascal}Service({pascal}Repository(db))
    deleted = await service.delete(id)

    if deleted is None:
        raise HTTPException(404, "{pascal} not found")

    return {{"message": "{pascal} deleted"}}
"""

    # 4. Write File & Update __init__.py
    write_new_file(file_path, template)
    update_init(layer_dir / "__init__.py", route_var, [route_var])

    console.print(f"[bold green]✨ Created route {route_var} at {file_path}[/bold green]")
    console.print(
        f"\n[yellow]Reminder:[/yellow] mount the new router in [bold]core/api_versions.py[/bold]:\n"
        f"    [cyan]from {domain}.routes import {route_var}[/cyan]\n"
        f"    [cyan]v1_router.include_router({route_var})[/cyan]"
    )


def main() -> None:
    typer.run(create_route)


if __name__ == "__main__":
    main()
