"""
Regression tests for the non-atomic two-write bug fixed across verify_email,
reset_password, and delete_user: a dependent user-row write followed by a
revoked-token insert used to commit independently, so a failure on the
second write left the first one already persisted.

The fix is auto_commit=False on both repository calls plus a single
caller-owned db.commit()/rollback(). These tests exercise that mechanism
directly — the exact user_repo.update()/delete()(auto_commit=False) ->
token_repo.add(auto_commit=False) -> db.commit()/rollback() sequence the
routes now use — rather than through the HTTP routes: verify_email's and
reset_password's own exists() guard rejects a second submission before the
route ever reaches the write pair, so the underlying race can't be
reproduced end-to-end without manufacturing true request concurrency over
one connection.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from auth.repositories.revoked_token_repository import RevokedTokenRepository
from core.factories.user_factory import make_email
from user.repositories.user_repository import UserRepository


async def test_update_rolls_back_when_paired_token_write_fails(db) -> None:
    """Mirrors verify_email/reset_password's write pair."""
    user_repo = UserRepository(db)
    token_repo = RevokedTokenRepository(db)

    user = await user_repo.add("Atomic Update", make_email(), "hash")
    assert user.is_verified is False

    jti = uuid.uuid4().hex
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    await token_repo.add(jti, expires_at)  # pre-seed a jti collision

    await user_repo.update(id=user.id, is_verified=True, auto_commit=False)

    with pytest.raises(ValueError, match="Token already used"):
        try:
            await token_repo.add(jti, expires_at, auto_commit=False)
            await db.commit()
        except ValueError:
            await db.rollback()
            raise

    reverted = await user_repo.get(user.id)
    assert reverted is not None
    assert reverted.is_verified is False


async def test_delete_rolls_back_when_paired_token_write_fails(db) -> None:
    """Mirrors delete_user's write pair (service.delete -> revoke_tokens)."""
    user_repo = UserRepository(db)
    token_repo = RevokedTokenRepository(db)

    user = await user_repo.add("Atomic Delete", make_email(), "hash")
    assert user.is_active is True

    jti = uuid.uuid4().hex
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    await token_repo.add(jti, expires_at)  # pre-seed a jti collision

    await user_repo.delete(user.id, auto_commit=False)

    with pytest.raises(ValueError, match="Token already used"):
        try:
            await token_repo.add(jti, expires_at, auto_commit=False)
            await db.commit()
        except ValueError:
            await db.rollback()
            raise

    reverted = await user_repo.get(user.id)
    assert reverted is not None
    assert reverted.is_active is True


async def test_add_duplicate_jti_raises_cleanly_without_caller_rollback(db) -> None:
    """Direct regression test for the containment bug: a duplicate jti must raise
    ValueError from inside add()'s own savepoint, leaving the outer transaction
    (and any earlier write in it) healthy — no PendingRollbackError, and no
    caller-side db.rollback() required to keep using the session."""
    user_repo = UserRepository(db)
    token_repo = RevokedTokenRepository(db)

    user = await user_repo.add(
        "Containment Check", make_email(), "hash", auto_commit=False
    )

    jti = uuid.uuid4().hex
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    await token_repo.add(jti, expires_at, auto_commit=False)

    with pytest.raises(ValueError, match="Token already used"):
        await token_repo.add(jti, expires_at, auto_commit=False)

    # No db.rollback() here — the outer transaction must still be usable.
    await db.commit()

    committed_user = await user_repo.get(user.id)
    assert committed_user is not None
