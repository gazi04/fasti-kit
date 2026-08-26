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


def create_service(
    domain: str = typer.Option(None, "--domain", "-d", help="Target domain folder"),
    name: str = typer.Option(None, "--name", "-n", help="Entity/Service name"),
    fields: str = typer.Option(
        None, "--fields", "-f", help="Ignored for services, kept for CLI consistency"
    ),
) -> None:
    """Scaffold a new service interactively or via CLI flags."""

    # 1. Interactive Prompts
    if not domain:
        domain = Prompt.ask(
            "[bold blue]Enter domain name[/bold blue] (e.g., inventory)"
        )
    if not name:
        name = Prompt.ask("[bold blue]Enter service name[/bold blue] (e.g., product)")

    # 2. Setup Variables
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)

    # 3. Generate Content
    layer_dir = Path(domain) / "services"
    file_path = layer_dir / f"{snake}_service.py"

    template = f"""from typing import Optional
from uuid import UUID

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

    async def get(self, id: UUID) -> Optional[{pascal}]:
        return await self.repo.get(id)

    async def update(self, id: UUID, data: Update{pascal}Request) -> Optional[{pascal}]:
        return await self.repo.update(id=id, **data.model_dump(exclude_unset=True))

    async def delete(
        self, id: UUID, force: bool = False, auto_commit: bool = True
    ) -> Optional[{pascal}]:
        if force:
            return await self.repo.force_delete(id, auto_commit=auto_commit)

        return await self.repo.delete(id, auto_commit=auto_commit)
"""

    # 4. Write File & Update __init__.py
    write_new_file(file_path, template)
    update_init(layer_dir / "__init__.py", f"{snake}_service", [f"{pascal}Service"])

    console.print(
        f"[bold green]✨ Created service {pascal}Service at {file_path}[/bold green]"
    )


def main() -> None:
    typer.run(create_service)


if __name__ == "__main__":
    main()
