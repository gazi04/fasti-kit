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
    require_domain,
    resolve_names,
    update_init,
    write_new_file,
)


def generate_entity(domain: str, name: str, fields: str = "") -> list[Path]:
    snake, pascal = resolve_names(domain, name)
    parsed_fields = parse_fields(fields)

    entity_fields = "\n    ".join(
        [f"{f['name']}: {f['py_type']}" for f in parsed_fields]
    )
    if not entity_fields:
        entity_fields = "# TODO: add domain-specific fields here (e.g. name: str)"

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
    return [file_path, update_init(layer_dir / "__init__.py", snake, [pascal])]


def create_entity(
    domain: str | None = typer.Option(
        None, "--domain", "-d", help="Target domain folder"
    ),
    name: str | None = typer.Option(None, "--name", "-n", help="Entity name"),
    fields: str | None = typer.Option(
        None, "--fields", "-f", help="Fields: name:str,price:float"
    ),
) -> None:
    """Scaffold a new entity interactively or via CLI flags."""
    domain = ask_domain(domain)
    name = ask_name(name, "entity")
    fields = ask_fields(fields)

    with cli_errors():
        require_domain(domain)
        paths = generate_entity(domain, name, fields)

    format_paths(paths)
    console.print(
        f"[bold green]✨ Entity {name} is ready in {domain}/entities[/bold green]"
    )


def main() -> None:
    typer.run(create_entity)


if __name__ == "__main__":
    main()
