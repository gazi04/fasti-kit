from pathlib import Path

import typer
from rich.panel import Panel

from scripts._boilerplate import (
    ask_domain,
    ask_fields,
    ask_name,
    cli_errors,
    console,
    format_paths,
    register_model,
    register_router,
    resolve_names,
)
from scripts.create_dependencies import generate_dependencies
from scripts.create_domain import generate_domain
from scripts.create_entity import generate_entity
from scripts.create_model import generate_model
from scripts.create_repository import generate_repository
from scripts.create_route import generate_route
from scripts.create_schema import generate_schema
from scripts.create_service import generate_service

LAYER_GENERATORS = (
    generate_entity,
    generate_model,
    generate_repository,
    generate_schema,
    generate_service,
    generate_route,
)


def generate_all(domain: str, name: str, fields: str = "") -> list[Path]:
    """Generate every layer for `name` in `domain` and wire it into the app."""
    snake, pascal = resolve_names(domain, name)

    paths = generate_domain(domain)
    for generate in LAYER_GENERATORS:
        paths += generate(domain, name, fields)
    paths += generate_dependencies(domain, name)
    paths += register_model(domain, f"{pascal}Model")
    paths += register_router(domain, f"{snake}_router")
    return paths


def create_all(
    domain: str | None = typer.Option(
        None, "--domain", "-d", help="Target domain folder"
    ),
    name: str | None = typer.Option(None, "--name", "-n", help="Entity/Component name"),
    fields: str | None = typer.Option(
        None, "--fields", "-f", help="Fields: name:str,price:float"
    ),
) -> None:
    """Scaffold entity/model/repository/schema/service/route in one go."""
    domain = ask_domain(domain)
    name = ask_name(name, "component")
    fields = ask_fields(fields)

    console.print(
        Panel.fit(
            f"[bold magenta]🚀 Scaffolding '{name}' in domain '{domain}'[/bold magenta]",
            border_style="magenta",
        )
    )

    with cli_errors():
        paths = generate_all(domain, name, fields)

    format_paths(paths)

    console.print(
        f"\n[bold green]🎉 '{name}' is generated and wired into the app.[/bold green]"
    )
    console.print(
        "Next:\n"
        f'  [cyan]uv run create-migration -m "add {name}" -d {domain}[/cyan]\n'
        f"  [cyan]uv run create-test -d {domain} -n {name}[/cyan]"
    )


def main() -> None:
    typer.run(create_all)


if __name__ == "__main__":
    main()
