"""
Integration tests for the User domain: repository, service, and routes.

These tests run inside the transactional db fixture (savepoint rollback),
so all writes are automatically discarded after each test.
"""

import uuid

import pytest
from authx import TokenPayload
from fastapi import HTTPException

from auth.dependencies import auth
from core.factories.user_factory import (
    CreateUserRequestFactory,
    UpdateUserRequestFactory,
    make_email,
)
from core.setting import get_settings
from user.dependencies import get_current_user
from user.entities.user import User
from user.repositories.user_repository import UserRepository
from user.services.user_service import UserService

# ---------------------------------------------------------------------------
# UserRepository - direct DB tests
# ---------------------------------------------------------------------------


async def test_repository_add_and_get(db) -> None:
    """add() persists a user; get() retrieves it by id."""
    repo = UserRepository(db)
    email = make_email()

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
    email = make_email()
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
    email = make_email()
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


async def test_repository_update_can_clear_nullable_field(db) -> None:
    """update() writes None through to nullable columns.

    The old "skip None values" guard was removed on purpose so pending token
    fields can be cleared once consumed — see the verify-email/reset-password
    flows in auth_router.py.
    """
    repo = UserRepository(db)
    email = make_email()
    user = await repo.add("Dana Kept", email, "hashed_pw")

    seeded = await repo.update(user.id, pending_verification_jti="abc123")
    assert seeded is not None
    assert seeded.pending_verification_jti == "abc123"

    cleared = await repo.update(user.id, pending_verification_jti=None)
    assert cleared is not None
    assert cleared.pending_verification_jti is None
    assert cleared.full_name == "Dana Kept"  # untouched fields survive


async def test_repository_soft_delete(db) -> None:
    """delete() marks the user inactive rather than removing the row."""
    repo = UserRepository(db)
    email = make_email()
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
    email = make_email()
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
    email = make_email()
    await repo.add("First", email, "pw1")

    with pytest.raises(ValueError, match="Email taken"):
        await repo.add("Second", email, "pw2")


# ---------------------------------------------------------------------------
# UserService - business logic layer
# ---------------------------------------------------------------------------


async def test_service_register_hashes_password(db) -> None:
    """register() stores a bcrypt hash, not the raw password."""
    service = UserService(UserRepository(db))
    data = CreateUserRequestFactory.build(password="plaintext")

    user = await service.register(data)

    assert user.password_hash != "plaintext"
    assert user.password_hash.startswith("$2b$")


async def test_service_get_returns_user(db) -> None:
    """get() delegates to the repository and returns an entity."""
    repo = UserRepository(db)
    service = UserService(repo)
    email = make_email()
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
    email = make_email()
    created = await repo.add("Iris Update", email, "old_hash")

    data = UpdateUserRequestFactory.build(password="new_plain")
    updated = await service.update(created.id, data)
    assert updated is not None
    assert updated.password_hash != "new_plain"
    assert updated.password_hash.startswith("$2b$")


async def test_service_update_skips_password_when_none(db) -> None:
    """update() does not re-hash when no new password is supplied."""
    repo = UserRepository(db)
    service = UserService(repo)
    email = make_email()
    created = await repo.add("Jack NoPass", email, "original_hash")

    data = UpdateUserRequestFactory.build(full_name="Jack Updated")
    updated = await service.update(created.id, data)
    assert updated is not None
    assert updated.full_name == "Jack Updated"


async def test_service_delete_soft(db) -> None:
    """delete() (no force) soft-deletes the user."""
    repo = UserRepository(db)
    service = UserService(repo)
    email = make_email()
    created = await repo.add("Karen Del", email, "pw")

    deleted = await service.delete(created.id)
    assert deleted is not None
    assert deleted.is_active is False


async def test_service_force_delete(db) -> None:
    """delete(force=True) calls force_delete and removes the row."""
    repo = UserRepository(db)
    service = UserService(repo)
    email = make_email()
    created = await repo.add("Leo Force", email, "pw")

    result = await service.delete(created.id, force=True)
    assert result is not None

    gone = await repo.get(created.id)
    assert gone is None


# ---------------------------------------------------------------------------
# get_current_user dependency
#
# Called directly (repo + payload arguments) rather than over HTTP so the
# test does not go through authx's blocklist callback, which opens its own
# AsyncSessionLocal against the dev database instead of the test database.
# ---------------------------------------------------------------------------


def _payload_for(user_id: uuid.UUID) -> TokenPayload:
    token = auth.create_access_token(uid=str(user_id))
    settings = get_settings()
    return TokenPayload.decode(
        token,
        key=settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        verify=True,
    )


async def test_get_current_user_returns_active_user(db) -> None:
    repo = UserRepository(db)
    created = await repo.add("Mia Current", make_email(), "pw")

    current = await get_current_user(user_repo=repo, payload=_payload_for(created.id))

    assert current.id == created.id
    assert current.is_active is True


async def test_get_current_user_raises_404_for_unknown_sub(db) -> None:
    repo = UserRepository(db)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(user_repo=repo, payload=_payload_for(uuid.uuid4()))

    assert exc_info.value.status_code == 404


async def test_get_current_user_raises_403_for_deactivated_user(db) -> None:
    repo = UserRepository(db)
    created = await repo.add("Nina Deleted", make_email(), "pw")
    await repo.update(created.id, is_active=False)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(user_repo=repo, payload=_payload_for(created.id))

    assert exc_info.value.status_code == 403
