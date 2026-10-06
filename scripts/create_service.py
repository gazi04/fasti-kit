from pathlib import Path

import typer

from scripts._boilerplate import (
    ask_domain,
    ask_name,
    cli_errors,
    console,
    format_paths,
    require_domain,
    resolve_names,
    update_init,
    write_new_file,
)


def generate_service(domain: str, name: str, fields: str = "") -> list[Path]:
    snake, pascal = resolve_names(domain, name)

    layer_dir = Path(domain) / "services"
    file_path = layer_dir / f"{snake}_service.py"

    template = f"""from uuid import UUID

from fastapi_pagination.cursor import CursorPage, CursorParams

from {domain}.entities.{snake} import {pascal}
from {domain}.repositories.{snake}_repository import {pascal}Repository
from {domain}.schemas.{snake}_schema import Create{pascal}Request, Update{pascal}Request


class {pascal}Service:
    def __init__(self, repo: {pascal}Repository) -> None:
        self.repo = repo

    async def create(
        self, data: Create{pascal}Request, auto_commit: bool = True
    ) -> {pascal}:
        return await self.repo.add(**data.model_dump(), auto_commit=auto_commit)

    async def get(self, id: UUID) -> {pascal} | None:
        return await self.repo.get(id)

    async def update(self, id: UUID, data: Update{pascal}Request) -> {pascal} | None:
        return await self.repo.update(id=id, **data.model_dump(exclude_unset=True))

    async def delete(
        self, id: UUID, force: bool = False, auto_commit: bool = True
    ) -> {pascal} | None:
        if force:
            return await self.repo.force_delete(id, auto_commit=auto_commit)

        return await self.repo.delete(id, auto_commit=auto_commit)

    async def list(self, params: CursorParams | None = None) -> CursorPage[{pascal}]:
        return await self.repo.list(params)
"""

    write_new_file(file_path, template)
    init = update_init(
        layer_dir / "__init__.py", f"{snake}_service", [f"{pascal}Service"]
    )
    return [file_path, init]


def create_service(
    domain: str | None = typer.Option(
        None, "--domain", "-d", help="Target domain folder"
    ),
    name: str | None = typer.Option(None, "--name", "-n", help="Entity/Service name"),
    fields: str | None = typer.Option(
        None, "--fields", "-f", help="Ignored for services, kept for CLI consistency"
    ),
) -> None:
    """Scaffold a new service interactively or via CLI flags."""
    domain = ask_domain(domain)
    name = ask_name(name, "service")

    with cli_errors():
        require_domain(domain)
        paths = generate_service(domain, name)

    format_paths(paths)
    console.print(
        f"[bold green]✨ Service for {name} is ready in {domain}/services[/bold green]"
    )


def main() -> None:
    typer.run(create_service)


if __name__ == "__main__":
    main()
