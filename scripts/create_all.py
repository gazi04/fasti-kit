import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from scripts.create_domain import create_domain
from scripts.create_entity import create_entity
from scripts.create_model import create_model
from scripts.create_repository import create_repository
from scripts.create_route import create_route
from scripts.create_schema import create_schema
from scripts.create_service import create_service

console = Console()


def create_all(
    domain: str = typer.Option(None, "--domain", "-d", help="Target domain folder"),
    name: str = typer.Option(None, "--name", "-n", help="Entity/Component name"),
    fields: str = typer.Option(
        None, "--fields", "-f", help="Fields: name:str,price:float"
    ),
) -> None:
    """Scaffold entity/model/repository/schema/service/route in one go."""

    # 1. Prompt once upfront so the user isn't asked repeatedly
    if not domain:
        domain = Prompt.ask(
            "[bold blue]Enter domain name[/bold blue] (e.g., inventory)"
        )
    if not name:
        name = Prompt.ask("[bold blue]Enter component name[/bold blue] (e.g., product)")
    if fields is None:
        console.print("[dim]Supported types: str, int, float, bool, uuid[/dim]")
        fields = Prompt.ask(
            "[bold blue]Enter fields[/bold blue] (e.g., title:str,price:float) or leave blank",
            default="",
        )

    console.print(
        Panel.fit(
            f"[bold magenta]🚀 Scaffolding complete feature for '{name}' in domain '{domain}'[/bold magenta]",
            border_style="magenta",
        )
    )

    # 2. Invoke all generators with keyword arguments
    create_domain(domain=domain)
    create_entity(domain=domain, name=name, fields=fields)
    create_model(domain=domain, name=name, fields=fields)
    create_repository(domain=domain, name=name, fields=fields)
    create_schema(domain=domain, name=name, fields=fields)
    create_service(domain=domain, name=name, fields=fields)
    create_route(domain=domain, name=name, fields=fields)

    console.print(
        f"\n[bold green]🎉 All components for '{name}' scaffolded successfully![/bold green]\n"
    )


def main() -> None:
    typer.run(create_all)


if __name__ == "__main__":
    main()
