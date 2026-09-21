import re
from pathlib import Path

import typer
from alembic.config import Config
from rich.console import Console

from alembic import command
from core.safety import SafetyError, ensure_safe_operation

console = Console()

MODELS_MANIFEST = Path("core/models.py")


def _check_domain_registered(domain: str, manifest_source: str) -> None:
    """Raise if `core/models.py` never imports the domain's models module.

    `alembic/env.py`'s `target_metadata = Base.metadata` is only populated by
    that manifest import — a missing entry means autogenerate silently
    produces an empty (or wrong) migration with no error.
    """
    if f"from {domain}.models import" not in manifest_source:
        raise typer.BadParameter(
            f"core/models.py doesn't import {domain}.models — Alembic won't see "
            f"its tables. Add a line like 'from {domain}.models import "
            f"{domain.capitalize()}Model' to core/models.py first, then re-run.",
            param_hint="--domain",
        )


def _lint_migration_file(content: str) -> list[str]:
    """Advisory-only checks for common autogenerate footguns."""
    warnings = []

    if "op." not in content:
        warnings.append(
            "No schema changes detected — check the domain is registered in "
            "core/models.py."
        )
    if "op.drop_column" in content:
        warnings.append(
            "Dropping a column — make sure any data worth keeping has been "
            "migrated out first."
        )
    if "op.drop_table" in content:
        warnings.append(
            "Dropping a table — this is irreversible once applied; double "
            "check downgrade() restores it if you need a safety net."
        )
    if re.search(r"nullable=False", content) and "server_default" not in content:
        warnings.append(
            "Adding/altering a column to nullable=False with no server_default "
            "— existing rows may fail to backfill."
        )

    return warnings


def create_migration(
    message: str = typer.Option(..., "--message", "-m", help="Migration message"),
    domain: str = typer.Option(
        None,
        "--domain",
        "-d",
        help="Domain whose core/models.py registration to verify",
    ),
    allow_production: bool = typer.Option(
        False, "--allow-production", help="Allow running against production"
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Also run 'alembic upgrade head' after generating"
    ),
) -> None:
    """Generate an Alembic migration with pre-flight and post-generation guardrails."""
    try:
        ensure_safe_operation("create-migration", allow_production=allow_production)
    except SafetyError as err:
        console.print(f"[bold red]ERROR:[/bold red] {err}")
        raise typer.Exit(1) from err

    if domain:
        _check_domain_registered(domain, MODELS_MANIFEST.read_text())

    try:
        import core.models  # noqa: F401 - side effect: populates Base.metadata
    except Exception as exc:
        console.print(
            f"[bold red]ERROR:[/bold red] core/models.py failed to import: {exc}"
        )
        raise typer.Exit(1) from exc

    cfg = Config("alembic.ini")
    script = command.revision(cfg, message=message, autogenerate=True)
    if isinstance(script, list):
        script = script[0] if script else None
    if script is None:
        console.print(
            "[yellow]No migration generated — nothing to autogenerate.[/yellow]"
        )
        return

    path = Path(script.path)
    console.print(f"[bold green]Created migration {path}[/bold green]")

    for warning in _lint_migration_file(path.read_text()):
        console.print(f"[yellow]Warning:[/yellow] {warning}")

    console.print("\n[dim]Review the generated file before applying it.[/dim]")

    if apply:
        command.upgrade(cfg, "head")
        console.print(
            "[bold green]Applied migration (alembic upgrade head).[/bold green]"
        )


def main() -> None:
    typer.run(create_migration)


if __name__ == "__main__":
    main()
