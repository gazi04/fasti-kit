import asyncio
from typing import Annotated

import typer
from sqlalchemy import delete

from auth.services.security_service import SecurityService
from core.database import AsyncSessionLocal
from core.factories.user_factory import CreateUserFactory
from core.safety import SafetyError, ensure_safe_operation
from user.models.user_model import UserModel
from user.repositories.user_repository import UserRepository

app = typer.Typer()


async def seed_database(
    count: int,
    admin_email: str,
    admin_password: str,
    unverified_count: int,
    reset: bool,
    force: bool,
) -> None:
    async with AsyncSessionLocal() as db:
        if reset:
            await db.execute(delete(UserModel))
            await db.commit()

        repo = UserRepository(db)
        used_emails: set[str] = set()

        for _ in range(count):
            request = CreateUserFactory.build()
            email = request.email
            while email in used_emails:
                request = CreateUserFactory.build()
                email = request.email

            used_emails.add(email)

            user = await repo.add(
                full_name=request.name,
                email=email,
                password_hash=SecurityService.hash_password(request.password),
            )

            await repo.update(user.id, is_verified=True, is_active=True)


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
        int, typer.Option(help="How many users stay unverified")
    ] = 0,
    reset: Annotated[
        bool, typer.Option("--reset", help="Truncate seeded tables first")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Seed even if tables are non-emtpy")
    ] = False,
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
            count, admin_email, admin_password, unverified_count, reset, force
        )
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
