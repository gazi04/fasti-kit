"""
Regression tests for the non-atomic two-write bug: a user-row write followed by
a revoked-token insert used to commit independently, so a failure on the second
write left the first one already persisted.

Each AccountRepository operation is now one transaction owned by the
repository. These tests pre-seed a jti collision so the token insert fails,
then check the user-row write rolled back with it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from auth.entities.auth_session import TokenRef
from auth.repositories.account_repository import AccountRepository
from auth.repositories.revoked_token_repository import RevokedTokenRepository
from core.exception import ConflictError
from core.factories.user_factory import make_email
from user.repositories.user_repository import UserRepository


def _expiry() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


async def test_verify_email_rolls_back_when_token_write_fails(db) -> None:
    user_repo = UserRepository(db)
    user = await user_repo.add("Atomic Verify", make_email(), "hash")
    assert user.is_verified is False

    jti = uuid.uuid4().hex
    await RevokedTokenRepository(db).add(jti, _expiry())

    with pytest.raises(ConflictError, match="Token already used"):
        await AccountRepository(db).verify_email(user.id, jti, _expiry())

    reverted = await user_repo.get(user.id)
    assert reverted is not None
    assert reverted.is_verified is False


async def test_reset_password_rolls_back_when_token_write_fails(db) -> None:
    user_repo = UserRepository(db)
    user = await user_repo.add("Atomic Reset", make_email(), "old_hash")

    jti = uuid.uuid4().hex
    await RevokedTokenRepository(db).add(jti, _expiry())

    with pytest.raises(ConflictError, match="Token already used"):
        await AccountRepository(db).reset_password(user.id, "new_hash", jti, _expiry())

    reverted = await user_repo.get(user.id)
    assert reverted is not None
    assert reverted.password_hash == "old_hash"


async def test_verify_email_commits_both_writes(db) -> None:
    user_repo = UserRepository(db)
    user = await user_repo.add("Atomic Happy", make_email(), "hash")
    jti = uuid.uuid4().hex

    await AccountRepository(db).verify_email(user.id, jti, _expiry())

    verified = await user_repo.get(user.id)
    assert verified is not None
    assert verified.is_verified is True
    assert await RevokedTokenRepository(db).exists(jti) is True


async def test_close_account_deactivates_and_revokes_in_one_transaction(db) -> None:
    user_repo = UserRepository(db)
    user = await user_repo.add("Atomic Close", make_email(), "hash")
    access, refresh = uuid.uuid4().hex, uuid.uuid4().hex

    closed = await AccountRepository(db).close_account(
        user.id, [TokenRef(access, _expiry()), TokenRef(refresh, _expiry())]
    )

    assert closed is not None
    assert closed.is_active is False
    token_repo = RevokedTokenRepository(db)
    assert await token_repo.exists(access) is True
    assert await token_repo.exists(refresh) is True


async def test_close_account_tolerates_an_already_revoked_token(db) -> None:
    user = await UserRepository(db).add("Atomic Twice", make_email(), "hash")
    jti = uuid.uuid4().hex
    await RevokedTokenRepository(db).add(jti, _expiry())

    closed = await AccountRepository(db).close_account(
        user.id, [TokenRef(jti, _expiry())]
    )

    assert closed is not None
    assert closed.is_active is False


async def test_close_account_returns_none_and_revokes_nothing_for_missing_user(
    db,
) -> None:
    jti = uuid.uuid4().hex

    closed = await AccountRepository(db).close_account(
        uuid.uuid4(), [TokenRef(jti, _expiry())]
    )

    assert closed is None
    assert await RevokedTokenRepository(db).exists(jti) is False


async def test_duplicate_jti_raises_and_leaves_the_session_usable(db) -> None:
    user_repo = UserRepository(db)
    token_repo = RevokedTokenRepository(db)
    user = await user_repo.add("Containment Check", make_email(), "hash")

    jti = uuid.uuid4().hex
    await token_repo.add(jti, _expiry())

    with pytest.raises(ConflictError, match="Token already used"):
        await token_repo.add(jti, _expiry())

    survivor = await user_repo.get(user.id)
    assert survivor is not None
