from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Prompt

from scripts._boilerplate import (
    parse_fields,
    to_pascal_case,
    to_snake_case,
    update_init,
    write_new_file,
)

console = Console()

def create_entity(
    domain: str = typer.Option(None, "--domain", "-d", help="Target domain folder"),
    name: str = typer.Option(None, "--name", "-n", help="Entity name"),
    fields: str = typer.Option(None, "--fields", "-f", help="Fields: name:str,price:float"),
) -> None:
    """Scaffold a new entity interactively or via CLI flags."""
    
    # 1. Interactive Prompts
    if not domain:
        domain = Prompt.ask("[bold blue]Enter domain name[/bold blue] (e.g., inventory)")
    if not name:
        name = Prompt.ask("[bold blue]Enter entity name[/bold blue] (e.g., product)")
    if fields is None:
        console.print("[dim]Supported types: str, int, float, bool, uuid[/dim]")
        fields = Prompt.ask(
            "[bold blue]Enter fields[/bold blue] (e.g., title:str,price:float) or leave blank", 
            default=""
        )

    # 2. Setup Variables
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)
    parsed_fields = parse_fields(fields)
    
    # 3. Format Fields String
    entity_fields = "\n    ".join([f"{f['name']}: {f['py_type']}" for f in parsed_fields])
    if not entity_fields:
        entity_fields = "# TODO: add domain-specific fields here (e.g. name: str)"

    # 4. Generate Content
    layer_dir = Path(domain) / "entities"
    file_path = layer_dir / f"{snake}.py"

    template = f"""import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class {pascal}:
    id: uuid.UUID
    {entity_fields}
    is_active: bool
    created_at: datetime
    updated_at: datetime
"""

    write_new_file(file_path, template)
    update_init(layer_dir / "__init__.py", snake, [pascal])
    
    console.print(f"[bold green]✨ Created entity {pascal} at {file_path}[/bold green]")


def main() -> None:
    typer.run(create_entity)


if __name__ == "__main__":
    main()
