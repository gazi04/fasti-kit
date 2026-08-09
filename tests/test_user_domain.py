"""
Integration tests for the User domain: repository, service, and routes.

These tests run inside the transactional db fixture (savepoint rollback),
so all writes are automatically discarded after each test.
"""

import uuid

import pytest

from user.entities.user import User
from user.repositories.user_repository import UserRepository
from user.schemas.user_schema import CreateUserRequest, UpdateUserRequest
from user.services.user_service import UserService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_email() -> str:
    """Generate a unique email address to avoid unique-constraint conflicts."""
    return f"test_{uuid.uuid4().hex[:8]}@example.com"


# ---------------------------------------------------------------------------
# UserRepository - direct DB tests
# ---------------------------------------------------------------------------


async def test_repository_add_and_get(db) -> None:
    """add() persists a user; get() retrieves it by id."""
    repo = UserRepository(db)
    email = _make_email()

    user = await repo.add("Alice Test", email, "hashed_pw")

    assert isinstance(user, User)
    assert user.email == email
    assert user.full_name == "Alice Test"
    assert user.id is not None

    fetched = await repo.get(user.id)
    assert fetched is not None
    assert fetched.id == user.id
    assert fetched.email == email


async def test_repository_get_returns_none_for_missing(db) -> None:
    """get() with an unknown UUID returns None without raising."""
    repo = UserRepository(db)
    result = await repo.get(uuid.uuid4())
    assert result is None


async def test_repository_get_by_email(db) -> None:
    """get_by_email() finds the user by email address."""
    repo = UserRepository(db)
    email = _make_email()
    await repo.add("Bob Test", email, "hashed_pw")

    found = await repo.get_by_email(email)
    assert found is not None
    assert found.email == email


async def test_repository_get_by_email_returns_none_for_missing(db) -> None:
    """get_by_email() returns None when the email doesn't exist."""
    repo = UserRepository(db)
    result = await repo.get_by_email("nobody@nowhere.invalid")
    assert result is None


async def test_repository_update_full_name(db) -> None:
    """update() applies arbitrary fields to an existing user."""
    repo = UserRepository(db)
    email = _make_email()
    user = await repo.add("Charlie Old", email, "hashed_pw")

    updated = await repo.update(user.id, full_name="Charlie New")
    assert updated is not None
    assert updated.full_name == "Charlie New"
    assert updated.email == email


async def test_repository_update_returns_none_for_missing(db) -> None:
    """update() with an unknown UUID returns None."""
    repo = UserRepository(db)
    result = await repo.update(uuid.uuid4(), full_name="Ghost")
    assert result is None


async def test_repository_update_skips_none_values(db) -> None:
    """update() does not overwrite fields whose value is None."""
    repo = UserRepository(db)
    email = _make_email()
    user = await repo.add("Dana Kept", email, "hashed_pw")

    updated = await repo.update(user.id, full_name=None, email=email)
    assert updated is not None
    assert updated.full_name == "Dana Kept"  # unchanged because None was skipped


async def test_repository_soft_delete(db) -> None:
    """delete() marks the user inactive rather than removing the row."""
    repo = UserRepository(db)
    email = _make_email()
    user = await repo.add("Eve Active", email, "hashed_pw")

    deleted = await repo.delete(user.id)
    assert deleted is not None
    assert deleted.is_active is False

    # Row still exists and is still fetchable
    still_there = await repo.get(user.id)
    assert still_there is not None
    assert still_there.is_active is False


async def test_repository_soft_delete_returns_none_for_missing(db) -> None:
    """delete() with an unknown UUID returns None."""
    repo = UserRepository(db)
    result = await repo.delete(uuid.uuid4())
    assert result is None


async def test_repository_force_delete(db) -> None:
    """force_delete() removes the row entirely."""
    repo = UserRepository(db)
    email = _make_email()
    user = await repo.add("Frank Force", email, "hashed_pw")

    deleted = await repo.force_delete(user.id)
    assert deleted is not None
    assert deleted.id == user.id

    gone = await repo.get(user.id)
    assert gone is None


async def test_repository_force_delete_returns_none_for_missing(db) -> None:
    """force_delete() with an unknown UUID returns None."""
    repo = UserRepository(db)
    result = await repo.force_delete(uuid.uuid4())
    assert result is None


async def test_repository_add_raises_on_duplicate_email(db) -> None:
    """add() raises ValueError when the email is already taken."""
    repo = UserRepository(db)
    email = _make_email()
    await repo.add("First", email, "pw1")

    with pytest.raises(ValueError, match="Email taken"):
        await repo.add("Second", email, "pw2")


# ---------------------------------------------------------------------------
# UserService - business logic layer
# ---------------------------------------------------------------------------


async def test_service_register_hashes_password(db) -> None:
    """register() stores a bcrypt hash, not the raw password."""
    service = UserService(UserRepository(db))
    data = CreateUserRequest(
        name="Grace Hash",
        email=_make_email(),
        password="plaintext",
    )

    user = await service.register(data)

    assert user.password_hash != "plaintext"
    assert user.password_hash.startswith("$2b$")


async def test_service_get_returns_user(db) -> None:
    """get() delegates to the repository and returns an entity."""
    repo = UserRepository(db)
    service = UserService(repo)
    email = _make_email()
    created = await repo.add("Henry Get", email, "pw")

    fetched = await service.get(created.id)
    assert fetched is not None
    assert fetched.id == created.id


async def test_service_get_returns_none_for_missing(db) -> None:
    """get() returns None when user is not found."""
    service = UserService(UserRepository(db))
    result = await service.get(uuid.uuid4())
    assert result is None


async def test_service_update_hashes_new_password(db) -> None:
    """update() hashes a new password via SecurityService before persisting."""
    repo = UserRepository(db)
    service = UserService(repo)
    email = _make_email()
    created = await repo.add("Iris Update", email, "old_hash")

    data = UpdateUserRequest(password="new_plain")
    updated = await service.update(created.id, data)
    assert updated is not None
    assert updated.password_hash != "new_plain"
    assert updated.password_hash.startswith("$2b$")


async def test_service_update_skips_password_when_none(db) -> None:
    """update() does not re-hash when no new password is supplied."""
    repo = UserRepository(db)
    service = UserService(repo)
    email = _make_email()
    created = await repo.add("Jack NoPass", email, "original_hash")

    data = UpdateUserRequest(full_name="Jack Updated")
    updated = await service.update(created.id, data)
    assert updated is not None
    assert updated.full_name == "Jack Updated"


async def test_service_delete_soft(db) -> None:
    """delete() (no force) soft-deletes the user."""
    repo = UserRepository(db)
    service = UserService(repo)
    email = _make_email()
    created = await repo.add("Karen Del", email, "pw")

    deleted = await service.delete(created.id)
    assert deleted is not None
    assert deleted.is_active is False


async def test_service_force_delete(db) -> None:
    """delete(force=True) calls force_delete and removes the row."""
    repo = UserRepository(db)
    service = UserService(repo)
    email = _make_email()
    created = await repo.add("Leo Force", email, "pw")

    result = await service.delete(created.id, force=True)
    assert result is not None

    gone = await repo.get(created.id)
    assert gone is None
