import asyncio
from typing import Annotated

import typer
from sqlalchemy.ext.asyncio import AsyncSession

from auth.services.security_service import SecurityService
from core.database import AsyncSessionLocal
from core.exception import ConflictError
from core.factories.user_factory import CreateUserRequestFactory
from core.safety import SafetyError, ensure_safe_operation
from user.repositories.user_repository import UserRepository
from user.schemas import CreateUserRequest

app = typer.Typer()

ADMIN_SCOPES = "admin:read admin:write"


def _build_unique_user(used_emails: set[str]) -> CreateUserRequest:
    request = CreateUserRequestFactory.build()
    while request.email in used_emails:
        request = CreateUserRequestFactory.build()
    used_emails.add(request.email)
    return request


async def _seed(
    db: AsyncSession,
    count: int,
    admin_email: str,
    admin_password: str,
    unverified_count: int,
    reset: bool,
    force: bool,
    password: str | None,
    email_prefix: str | None,
) -> None:
    repo = UserRepository(db)
    if reset:
        await repo.purge_all()

    user_count = await repo.count()
    if user_count and not reset and not force:
        typer.echo(
            f"ERROR: 'users' already has {user_count} row(s). "
            "Re-run with --reset to wipe first, or --force to append.",
            err=True,
        )
        raise typer.Exit(1)

    used_emails: set[str] = {admin_email}

    try:
        admin = await repo.add(
            full_name="Seed Admin",
            email=admin_email,
            password_hash=await SecurityService.hash_password(admin_password),
        )
        await repo.update(
            admin.id, is_verified=True, is_active=True, scopes=ADMIN_SCOPES
        )
    except ConflictError:
        typer.echo(f"Admin {admin_email!r} already exists — skipping.")

    shared_hash = await SecurityService.hash_password(password) if password else None
    skipped = 0
    for index in range(count):
        request = _build_unique_user(used_emails)
        try:
            user = await repo.add(
                full_name=request.name,
                email=f"{email_prefix}-{index}@example.com"
                if email_prefix
                else request.email,
                password_hash=shared_hash
                or await SecurityService.hash_password(request.password),
            )
        except ConflictError:
            skipped += 1
            continue
        await repo.update(user.id, is_verified=True, is_active=True)

    for _ in range(unverified_count):
        request = _build_unique_user(used_emails)
        await repo.add(
            full_name=request.name,
            email=request.email,
            password_hash=await SecurityService.hash_password(request.password),
        )

    typer.echo(
        f"Seeded: {count - skipped} verified ({skipped} already existed), "
        f"{unverified_count} unverified, admin {admin_email}"
    )


async def seed_database(
    count: int,
    admin_email: str,
    admin_password: str,
    unverified_count: int,
    reset: bool,
    force: bool,
    *,
    password: str | None = None,
    email_prefix: str | None = None,
    db: AsyncSession | None = None,
) -> None:
    args = (count, admin_email, admin_password, unverified_count, reset, force)
    if db is not None:
        await _seed(db, *args, password, email_prefix)
        return

    async with AsyncSessionLocal() as owned:
        await _seed(owned, *args, password, email_prefix)


@app.command()
def seed(
    count: Annotated[int, typer.Option(help="Number of regular users to create")] = 50,
    admin_email: Annotated[
        str, typer.Option(help="Known admin email")
    ] = "admin@example.com",
    admin_password: Annotated[
        str, typer.Option(help="Known admin password")
    ] = "admin123",
    unverified_count: Annotated[
        int, typer.Option(help="Extra users left unverified (in addition to --count)")
    ] = 0,
    reset: Annotated[
        bool, typer.Option("--reset", help="Truncate seeded tables first")
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Seed even if the users table is non-empty"),
    ] = False,
    password: Annotated[
        str | None,
        typer.Option(help="One password for every --count user (default: random each)"),
    ] = None,
    email_prefix: Annotated[
        str | None,
        typer.Option(
            help="Name --count users <prefix>-<n>@example.com; existing ones are skipped"
        ),
    ] = None,
    allow_production: Annotated[
        bool,
        typer.Option(
            "--allow-production", help="Allow seeding in the production environment"
        ),
    ] = False,
) -> None:
    try:
        ensure_safe_operation("seed", allow_production=allow_production)
    except SafetyError as err:
        typer.echo(f"ERROR: {err}", err=True)
        raise typer.Exit(1) from err

    asyncio.run(
        seed_database(
            count,
            admin_email,
            admin_password,
            unverified_count,
            reset,
            force,
            password=password,
            email_prefix=email_prefix,
        )
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
