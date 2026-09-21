from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Prompt

from scripts._boilerplate import to_pascal_case, to_snake_case, write_new_file

console = Console()


def create_factory(
    domain: str = typer.Option(None, "--domain", "-d", help="Target domain folder"),
    name: str = typer.Option(None, "--name", "-n", help="Entity/Factory name"),
    fields: str = typer.Option(
        None, "--fields", "-f", help="Ignored for factories, kept for CLI consistency"
    ),
) -> None:
    """Scaffold polyfactory request factories for a domain's schemas."""

    # 1. Interactive Prompts
    if not domain:
        domain = Prompt.ask(
            "[bold blue]Enter domain name[/bold blue] (e.g., inventory)"
        )
    if not name:
        name = Prompt.ask("[bold blue]Enter factory name[/bold blue] (e.g., product)")

    # 2. Setup Variables
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)

    # 3. Generate Content
    layer_dir = Path("core") / "factories"
    file_path = layer_dir / f"{snake}_factory.py"

    template = f"""from core.factories.base import BasePydanticFactory
from {domain}.schemas.{snake}_schema import Create{pascal}Request, Update{pascal}Request


class Create{pascal}RequestFactory(BasePydanticFactory[Create{pascal}Request]):
    __model__ = Create{pascal}Request
    __use_defaults__ = True


class Update{pascal}RequestFactory(BasePydanticFactory[Update{pascal}Request]):
    __model__ = Update{pascal}Request
    __use_defaults__ = True
"""

    # 4. Write File (core/factories has no __init__.py re-exports to update)
    write_new_file(file_path, template)

    console.print(
        f"[bold green]✨ Created factory Create{pascal}RequestFactory/"
        f"Update{pascal}RequestFactory at {file_path}[/bold green]"
    )


def main() -> None:
    typer.run(create_factory)


if __name__ == "__main__":
    main()
