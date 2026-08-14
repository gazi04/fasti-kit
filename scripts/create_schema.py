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


def create_schema(
    domain: str = typer.Option(None, "--domain", "-d", help="Target domain folder"),
    name: str = typer.Option(None, "--name", "-n", help="Entity/Schema name"),
    fields: str = typer.Option(None, "--fields", "-f", help="Fields: name:str,price:float"),
) -> None:
    """Scaffold new schemas interactively or via CLI flags."""

    # 1. Interactive Prompts
    if not domain:
        domain = Prompt.ask("[bold blue]Enter domain name[/bold blue] (e.g., inventory)")
    if not name:
        name = Prompt.ask("[bold blue]Enter schema name[/bold blue] (e.g., product)")
    if fields is None:
        console.print("[dim]Supported types: str, int, float, bool, uuid[/dim]")
        fields = Prompt.ask(
            "[bold blue]Enter fields[/bold blue] (e.g., title:str,price:float) or leave blank",
            default="",
        )

    # 2. Setup Variables
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)
    parsed_fields = parse_fields(fields)

    # 3. Format Fields String
    if parsed_fields:
        create_fields = "\n    ".join([f"{f['name']}: {f['py_type']}" for f in parsed_fields])
        update_fields = "\n    ".join([f"{f['name']}: Optional[{f['py_type']}] = None" for f in parsed_fields])
        response_fields = "\n    ".join([f"{f['name']}: {f['py_type']}" for f in parsed_fields]) + "\n    "
    else:
        create_fields = "# TODO: add domain-specific fields here (e.g. name: str)\n    pass"
        update_fields = "# TODO: add domain-specific fields here, all Optional\n    pass"
        response_fields = "# TODO: add domain-specific fields here (e.g. name: str)\n    "

    # 4. Generate Content
    layer_dir = Path(domain) / "schemas"
    file_path = layer_dir / f"{snake}_schema.py"

    template = f"""import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Create{pascal}Request(BaseModel):
    {create_fields}


class Update{pascal}Request(BaseModel):
    {update_fields}


class Get{pascal}Request(BaseModel):
    id: uuid.UUID


class {pascal}Response(BaseModel):
    id: uuid.UUID
    {response_fields}is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {{'from_attributes': True}}
"""

    # 5. Write Files & Update __init__.py
    write_new_file(file_path, template)
    update_init(
        layer_dir / "__init__.py",
        f"{snake}_schema",
        [
            f"Create{pascal}Request",
            f"Update{pascal}Request",
            f"Get{pascal}Request",
            f"{pascal}Response",
        ],
    )

    console.print(f"[bold green]✨ Created schemas for {pascal} at {file_path}[/bold green]")


def main() -> None:
    typer.run(create_schema)


if __name__ == "__main__":
    main()
