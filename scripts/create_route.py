from pathlib import Path

import typer

from scripts._boilerplate import (
    ask_domain,
    ask_name,
    cli_errors,
    console,
    format_paths,
    pluralize,
    require_domain,
    resolve_names,
    update_init,
    write_new_file,
)


def generate_route(domain: str, name: str, fields: str = "") -> list[Path]:
    snake, pascal = resolve_names(domain, name)
    route_var = f"{snake}_router"
    prefix = snake.replace("_", "-")

    layer_dir = Path(domain) / "routes"
    file_path = layer_dir / f"{route_var}.py"

    template = f"""from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi_pagination.cursor import CursorPage, CursorParams

from auth.dependencies import auth
from {domain}.dependencies import get_{snake}_service
from {domain}.entities.{snake} import {pascal}
from {domain}.schemas.{snake}_schema import (
    Create{pascal}Request,
    {pascal}Response,
    Update{pascal}Request,
)
from {domain}.services.{snake}_service import {pascal}Service

{route_var} = APIRouter(prefix="/{prefix}", tags=["{pascal}"])

requires_access_token = [
    Depends(auth.token_required(type="access", locations=["headers"]))
]


@{route_var}.post(
    "/create", response_model={pascal}Response, dependencies=requires_access_token
)
async def create_{snake}(
    data: Create{pascal}Request,
    service: {pascal}Service = Depends(get_{snake}_service),
) -> {pascal}:
    try:
        return await service.create(data)
    except ValueError as err:
        raise HTTPException(409, str(err)) from err


@{route_var}.get("/get/{{id}}", response_model={pascal}Response)
async def get_{snake}(
    id: UUID,
    service: {pascal}Service = Depends(get_{snake}_service),
) -> {pascal}:
    record = await service.get(id)

    if record is None:
        raise HTTPException(404, "{pascal} not found")

    return record


@{route_var}.patch(
    "/update/{{id}}", response_model={pascal}Response, dependencies=requires_access_token
)
async def update_{snake}(
    id: UUID,
    data: Update{pascal}Request,
    service: {pascal}Service = Depends(get_{snake}_service),
) -> {pascal}:
    try:
        record = await service.update(id, data)
    except ValueError as err:
        raise HTTPException(409, str(err)) from err

    if record is None:
        raise HTTPException(404, "{pascal} not found")

    return record


@{route_var}.delete("/delete/{{id}}", dependencies=requires_access_token)
async def delete_{snake}(
    id: UUID,
    service: {pascal}Service = Depends(get_{snake}_service),
) -> dict[str, str]:
    deleted = await service.delete(id)

    if deleted is None:
        raise HTTPException(404, "{pascal} not found")

    return {{"message": "{pascal} deleted"}}


@{route_var}.get("/list", response_model=CursorPage[{pascal}Response])
async def list_{pluralize(snake)}(
    params: CursorParams = Depends(),
    service: {pascal}Service = Depends(get_{snake}_service),
) -> CursorPage[{pascal}]:
    return await service.list(params)
"""

    write_new_file(file_path, template)
    init = update_init(layer_dir / "__init__.py", route_var, [route_var])
    return [file_path, init]


def create_route(
    domain: str | None = typer.Option(
        None, "--domain", "-d", help="Target domain folder"
    ),
    name: str | None = typer.Option(None, "--name", "-n", help="Entity/Route name"),
    fields: str | None = typer.Option(
        None, "--fields", "-f", help="Ignored for routes, kept for CLI consistency"
    ),
) -> None:
    """Scaffold a new route interactively or via CLI flags."""
    domain = ask_domain(domain)
    name = ask_name(name, "route")

    with cli_errors():
        require_domain(domain)
        paths = generate_route(domain, name)

    format_paths(paths)
    console.print(
        f"[bold green]✨ Routes for {name} are ready in {domain}/routes[/bold green]"
    )
    console.print(
        "[yellow]Reminder:[/yellow] the route needs its service factory in "
        f"{domain}/dependencies.py (`create-dependencies`) and a mount in "
        "core/api_versions.py. `create-all` does both for you."
    )


def main() -> None:
    typer.run(create_route)


if __name__ == "__main__":
    main()
