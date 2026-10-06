from pathlib import Path

import typer

from scripts._boilerplate import (
    ask_domain,
    ask_name,
    cli_errors,
    console,
    format_paths,
    resolve_names,
    write_new_file,
)


def generate_factory(domain: str, name: str) -> list[Path]:
    snake, pascal = resolve_names(domain, name)

    file_path = Path("core") / "factories" / f"{snake}_factory.py"

    template = f"""from core.factories.base import BasePydanticFactory
from {domain}.schemas.{snake}_schema import Create{pascal}Request, Update{pascal}Request


class Create{pascal}RequestFactory(BasePydanticFactory[Create{pascal}Request]):
    __model__ = Create{pascal}Request
    __use_defaults__ = True


class Update{pascal}RequestFactory(BasePydanticFactory[Update{pascal}Request]):
    __model__ = Update{pascal}Request
    __allow_none_optionals__ = False
"""

    write_new_file(file_path, template)
    return [file_path]


def create_factory(
    domain: str | None = typer.Option(
        None, "--domain", "-d", help="Target domain folder"
    ),
    name: str | None = typer.Option(None, "--name", "-n", help="Entity/Factory name"),
    fields: str | None = typer.Option(
        None, "--fields", "-f", help="Ignored for factories, kept for CLI consistency"
    ),
) -> None:
    """Scaffold polyfactory request factories for a domain's schemas."""
    domain = ask_domain(domain)
    name = ask_name(name, "factory")

    with cli_errors():
        paths = generate_factory(domain, name)

    format_paths(paths)
    console.print(
        f"[bold green]✨ Factories for {name} are ready in core/factories[/bold green]"
    )


def main() -> None:
    typer.run(create_factory)


if __name__ == "__main__":
    main()
