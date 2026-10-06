from pathlib import Path

import typer

from scripts._boilerplate import (
    ask_domain,
    cli_errors,
    console,
    register_pyproject,
    validate_domain,
)

DOMAIN_LAYERS = ("entities", "models", "repositories", "schemas", "services", "routes")


def generate_domain(domain: str) -> list[Path]:
    """Create a domain's six layer packages and wire it into pyproject.toml."""
    validate_domain(domain)
    root = Path(domain)

    for layer in DOMAIN_LAYERS:
        init = root / layer / "__init__.py"
        if not init.exists():
            init.parent.mkdir(parents=True, exist_ok=True)
            init.touch()
            print(f"created: {init}")

    dependencies = root / "dependencies.py"
    if not dependencies.exists():
        dependencies.touch()
        print(f"created: {dependencies}")

    return [dependencies, *register_pyproject(domain)]


def create_domain(
    domain: str | None = typer.Option(
        None, "--domain", "-d", help="Domain name, e.g. inventory"
    ),
) -> None:
    """Scaffold a new domain's layer packages and register it in pyproject.toml."""
    domain = ask_domain(domain)

    with cli_errors():
        generate_domain(domain)

    console.print(f"[bold green]✨ Domain {domain} is ready.[/bold green]")
    console.print(
        f"Next: [cyan]uv run create-all -d {domain} -n <entity> -f "
        "'title:str,price:float'[/cyan]"
    )


def main() -> None:
    typer.run(create_domain)


if __name__ == "__main__":
    main()
