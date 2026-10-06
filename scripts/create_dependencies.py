from pathlib import Path

import typer

from scripts._boilerplate import (
    ask_domain,
    ask_name,
    cli_errors,
    console,
    format_paths,
    merge_imports,
    require_domain,
    resolve_names,
)


def _required_imports(domain: str, snake: str, pascal: str) -> list[str]:
    return [
        "from fastapi import Depends",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "from core.database import get_db",
        f"from {domain}.repositories.{snake}_repository import {pascal}Repository",
        f"from {domain}.services.{snake}_service import {pascal}Service",
    ]


def _render_block(snake: str, pascal: str) -> str:
    return f"""def get_{snake}_repository(db: AsyncSession = Depends(get_db)) -> {pascal}Repository:
    return {pascal}Repository(db)


def get_{snake}_service(
    repo: {pascal}Repository = Depends(get_{snake}_repository),
) -> {pascal}Service:
    return {pascal}Service(repo)
"""


def generate_dependencies(domain: str, name: str) -> list[Path]:
    snake, pascal = resolve_names(domain, name)
    path = Path(domain) / "dependencies.py"
    content = path.read_text() if path.exists() else ""

    if f"def get_{snake}_service(" in content:
        print(f"skip: get_{snake}_service already exists in {path}")
        return [path]

    content = merge_imports(content, _required_imports(domain, snake, pascal))
    content = content.rstrip("\n") + "\n\n\n" + _render_block(snake, pascal)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"updated: {path}")
    return [path]


def create_dependencies(
    domain: str | None = typer.Option(
        None, "--domain", "-d", help="Target domain folder"
    ),
    name: str | None = typer.Option(None, "--name", "-n", help="Entity name"),
) -> None:
    """Add Depends() factories for an entity's repository and service."""
    domain = ask_domain(domain)
    name = ask_name(name, "entity")

    with cli_errors():
        require_domain(domain)
        paths = generate_dependencies(domain, name)

    format_paths(paths)
    console.print(
        f"[bold green]✨ Dependencies for {name} are ready in {domain}/dependencies.py[/bold green]"
    )


def main() -> None:
    typer.run(create_dependencies)


if __name__ == "__main__":
    main()
