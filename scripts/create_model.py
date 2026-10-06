from pathlib import Path

import typer

from scripts._boilerplate import (
    ask_domain,
    ask_fields,
    ask_name,
    cli_errors,
    console,
    format_paths,
    parse_fields,
    pluralize,
    require_domain,
    resolve_names,
    update_init,
    write_new_file,
)

_BASE_COLUMN_TYPES = {"Boolean", "DateTime"}


def generate_model(domain: str, name: str, fields: str = "") -> list[Path]:
    snake, pascal = resolve_names(domain, name)
    table_name = pluralize(snake)
    parsed_fields = parse_fields(fields)

    model_fields = "\n    ".join(
        [
            f"{f['name']}: Mapped[{f['py_type']}] = mapped_column({f['sqla_type']}"
            f"{', default=' + f['default'] if f['default'] else ''})"
            for f in parsed_fields
        ]
    )
    if not model_fields:
        model_fields = "# TODO: add domain-specific columns here"

    column_types = _BASE_COLUMN_TYPES | {
        f["sqla_type"] for f in parsed_fields if f["type"] != "uuid"
    }

    layer_dir = Path(domain) / "models"
    file_path = layer_dir / f"{snake}_model.py"

    template = f"""import uuid
from datetime import UTC, datetime

from sqlalchemy import {", ".join(sorted(column_types))}
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
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
"""

    write_new_file(file_path, template)
    init = update_init(layer_dir / "__init__.py", f"{snake}_model", [f"{pascal}Model"])
    return [file_path, init]


def create_model(
    domain: str | None = typer.Option(
        None, "--domain", "-d", help="Target domain folder"
    ),
    name: str | None = typer.Option(None, "--name", "-n", help="Entity/Model name"),
    fields: str | None = typer.Option(
        None, "--fields", "-f", help="Fields: name:str,price:float"
    ),
) -> None:
    """Scaffold a new ORM model interactively or via CLI flags."""
    domain = ask_domain(domain)
    name = ask_name(name, "model")
    fields = ask_fields(fields)

    with cli_errors():
        require_domain(domain)
        paths = generate_model(domain, name, fields)

    format_paths(paths)
    console.print(
        f"[bold green]✨ Model for {name} is ready in {domain}/models[/bold green]"
    )
    console.print(
        "[yellow]Reminder:[/yellow] `create-all` registers models in "
        "core/models.py for you; on its own, add the import there yourself."
    )


def main() -> None:
    typer.run(create_model)


if __name__ == "__main__":
    main()
