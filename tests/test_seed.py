import pytest
import typer
from sqlalchemy import func, select

from scripts.seed import seed_database
from user.models.user_model import UserModel

ADMIN_EMAIL = "seed-admin@example.com"
ADMIN_PASSWORD = "seed-admin-pw"


async def _count(db, *whereclauses) -> int:
    stmt = select(func.count()).select_from(UserModel)
    for clause in whereclauses:
        stmt = stmt.where(clause)
    return await db.scalar(stmt) or 0


async def test_seed_creates_admin_verified_and_unverified(db) -> None:
    """With --reset, seed_database wires up admin creation, --count verified users
    and the extra unverified batch: total rows = 1 admin + count + unverified_count."""
    await seed_database(
        count=2,
        admin_email=ADMIN_EMAIL,
        admin_password=ADMIN_PASSWORD,
        unverified_count=1,
        reset=True,
        force=False,
        db=db,
    )

    assert await _count(db) == 4
    assert await _count(db, UserModel.is_verified.is_(False)) == 1

    admin = await db.scalar(select(UserModel).where(UserModel.email == ADMIN_EMAIL))
    assert admin is not None
    assert admin.is_verified is True
    assert admin.is_active is True
    assert "admin:read" in admin.scopes


async def test_seed_admin_idempotent_under_force(db) -> None:
    """A second run with --force skips the already-present admin instead of crashing."""
    await seed_database(
        count=0,
        admin_email=ADMIN_EMAIL,
        admin_password=ADMIN_PASSWORD,
        unverified_count=0,
        reset=True,
        force=False,
        db=db,
    )
    await seed_database(
        count=0,
        admin_email=ADMIN_EMAIL,
        admin_password=ADMIN_PASSWORD,
        unverified_count=0,
        reset=False,
        force=True,
        db=db,
    )

    assert await _count(db, UserModel.email == ADMIN_EMAIL) == 1


async def test_seed_aborts_on_populated_table(db) -> None:
    """Non-empty users table + no --reset/--force -> typer.Exit, nothing seeded."""
    db.add(
        UserModel(full_name="Existing", email="existing@example.com", password_hash="x")
    )
    await db.commit()
    before = await _count(db)

    with pytest.raises(typer.Exit):
        await seed_database(
            count=1,
            admin_email=ADMIN_EMAIL,
            admin_password=ADMIN_PASSWORD,
            unverified_count=0,
            reset=False,
            force=False,
            db=db,
        )

    assert await _count(db) == before
