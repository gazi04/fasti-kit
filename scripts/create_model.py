from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Prompt

from scripts._boilerplate import (
    parse_fields,
    pluralize,
    to_pascal_case,
    to_snake_case,
    update_init,
    write_new_file,
)

console = Console()


def create_model(
    domain: str = typer.Option(None, "--domain", "-d", help="Target domain folder"),
    name: str = typer.Option(None, "--name", "-n", help="Entity/Model name"),
    fields: str = typer.Option(None, "--fields", "-f", help="Fields: name:str,price:float"),
) -> None:
    """Scaffold a new ORM model interactively or via CLI flags."""
    
    # 1. Interactive Prompts
    if not domain:
        domain = Prompt.ask("[bold blue]Enter domain name[/bold blue] (e.g., inventory)")
    if not name:
        name = Prompt.ask("[bold blue]Enter model name[/bold blue] (e.g., product)")
    if fields is None:
        console.print("[dim]Supported types: str, int, float, bool, uuid[/dim]")
        fields = Prompt.ask(
            "[bold blue]Enter fields[/bold blue] (e.g., title:str,price:float) or leave blank", 
            default=""
        )

    # 2. Setup Variables
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)
    table_name = pluralize(snake)
    parsed_fields = parse_fields(fields)

    # 3. Format Fields String
    model_fields = "\n    ".join(
        [
            f"{f['name']}: Mapped[{f['py_type']}] = mapped_column({f['sqla_type']}"
            f"{', default=' + f['default'] if f['default'] else ''})" 
            for f in parsed_fields
        ]
    )
    if not model_fields:
        model_fields = "# TODO: add domain-specific columns here (e.g. name: Mapped[str] = mapped_column(String(255)))"

    # 4. Generate Content
    layer_dir = Path(domain) / "models"
    file_path = layer_dir / f"{snake}_model.py"

    template = f"""import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Integer, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class {pascal}Model(Base):
    __tablename__ = "{table_name}"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    {model_fields}

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
"""

    # 5. Write Files & Update __init__.py
    write_new_file(file_path, template)
    update_init(layer_dir / "__init__.py", f"{snake}_model", [f"{pascal}Model"])

    console.print(f"[bold green]✨ Created model {pascal}Model at {file_path}[/bold green]")
    console.print(
        f"\n[yellow]Reminder:[/yellow] register the new model for Alembic/metadata discovery - "
        f"add this line to [bold]core/models.py[/bold]:\n"
        f"    [cyan]from {domain}.models import {pascal}Model[/cyan]"
    )


def main() -> None:
    typer.run(create_model)


if __name__ == "__main__":
    main()
