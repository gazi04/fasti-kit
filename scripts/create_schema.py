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


def generate_schema(domain: str, name: str, fields: str = "") -> list[Path]:
    snake, pascal = resolve_names(domain, name)
    parsed_fields = parse_fields(fields)

    if parsed_fields:
        create_fields = "\n    ".join(
            [f"{f['name']}: {f['py_type']}" for f in parsed_fields]
        )
        update_fields = "\n    ".join(
            [f"{f['name']}: {f['py_type']} | None = None" for f in parsed_fields]
        )
        response_fields = (
            "\n    ".join([f"{f['name']}: {f['py_type']}" for f in parsed_fields])
            + "\n    "
        )
    else:
        create_fields = (
            "# TODO: add domain-specific fields here (e.g. name: str)\n    pass"
        )
        update_fields = (
            "# TODO: add domain-specific fields here, all optional\n    pass"
        )
        response_fields = (
            "# TODO: add domain-specific fields here (e.g. name: str)\n    "
        )

    layer_dir = Path(domain) / "schemas"
    file_path = layer_dir / f"{snake}_schema.py"

    template = f"""import uuid
from datetime import datetime

from pydantic import BaseModel


class Create{pascal}Request(BaseModel):
    {create_fields}


class Update{pascal}Request(BaseModel):
    {update_fields}


class {pascal}Response(BaseModel):
    id: uuid.UUID
    {response_fields}is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {{"from_attributes": True}}
"""

    write_new_file(file_path, template)
    init = update_init(
        layer_dir / "__init__.py",
        f"{snake}_schema",
        [f"Create{pascal}Request", f"Update{pascal}Request", f"{pascal}Response"],
    )
    return [file_path, init]


def create_schema(
    domain: str | None = typer.Option(
        None, "--domain", "-d", help="Target domain folder"
    ),
    name: str | None = typer.Option(None, "--name", "-n", help="Entity/Schema name"),
    fields: str | None = typer.Option(
        None, "--fields", "-f", help="Fields: name:str,price:float"
    ),
) -> None:
    """Scaffold new schemas interactively or via CLI flags."""
    domain = ask_domain(domain)
    name = ask_name(name, "schema")
    fields = ask_fields(fields)

    with cli_errors():
        require_domain(domain)
        paths = generate_schema(domain, name, fields)

    format_paths(paths)
    console.print(
        f"[bold green]✨ Schemas for {name} are ready in {domain}/schemas[/bold green]"
    )


def main() -> None:
    typer.run(create_schema)


if __name__ == "__main__":
    main()
