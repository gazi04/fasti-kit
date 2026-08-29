"""
Regression tests for the replica read/write split fixes.

Covers the three defects that lived in the untested gap between
tests/test_db_routing.py (which unit-tests get_bind()'s *decision*) and the
rest of the suite (which, before the conftest rewrite, bypassed the routing
session entirely):

- the failover only wrapped execute(), missing scalar()/get()
- the failover's rollback could expunge pending, unflushed writes
- RevokedTokenRepository.exists() pinned the whole request to primary
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from auth.repositories.revoked_token_repository import RevokedTokenRepository
from core.database import force_primary_var
from core.factories.user_factory import UserModelFactory, make_email
from user.models import UserModel
from user.repositories.user_repository import UserRepository


@pytest.fixture(autouse=True)
def _reset_force_primary():
    token = force_primary_var.set(False)
    yield
    force_primary_var.reset(token)


def _operational_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("replica is down"))


# ---------------------------------------------------------------------------
# Finding 3 — failover must cover the read APIs the repositories actually use
# ---------------------------------------------------------------------------


async def test_scalar_fails_over_to_primary(db, monkeypatch) -> None:
    """db.scalar() bypasses execute(), so it needs its own failover wrapper."""
    calls = {"n": 0}
    real_scalar = AsyncSession.scalar

    async def flaky_scalar(self, statement, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _operational_error()
        return await real_scalar(self, statement, *args, **kwargs)

    # Patch the *base* method the override delegates to, so _with_failover
    # still runs. Patching the override itself would bypass the wrapper.
    monkeypatch.setattr(AsyncSession, "scalar", flaky_scalar)

    await db.scalar(select(UserModel.id).limit(1))

    assert calls["n"] == 2, "scalar() should have been retried once"
    assert force_primary_var.get() is True, "retry must pin to primary"


async def test_get_fails_over_to_primary(db, monkeypatch) -> None:
    """db.get() bypasses execute() too."""
    calls = {"n": 0}
    real_get = AsyncSession.get

    async def flaky_get(self, entity, ident, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _operational_error()
        return await real_get(self, entity, ident, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "get", flaky_get)

    await db.get(UserModel, uuid.uuid4())

    assert calls["n"] == 2
    assert force_primary_var.get() is True


# ---------------------------------------------------------------------------
# Finding 4 — the failover must never roll away work the session is holding
# ---------------------------------------------------------------------------


async def test_failover_declines_while_pending_write_is_unflushed(db) -> None:
    """A pending, unflushed insert must veto the failover.

    autoflush is off, so db.add() leaves an instance pending with no write
    flag set. Rolling back to retry would expunge it, the retry would succeed,
    and the eventual commit would write nothing.
    """
    email = make_email()
    db.add(UserModelFactory.build(email=email))

    assert force_primary_var.get() is False, "no flush yet, so no pin yet"
    assert db._can_fail_over() is False, "pending write must veto failover"

    # The pending instance survives, and still commits.
    await db.commit()
    found = await db.scalar(select(UserModel).where(UserModel.email == email))
    assert found is not None


async def test_failover_declines_after_a_write_pinned_the_request(db) -> None:
    repo = UserRepository(db)
    await repo.add("Already Written", make_email(), "pw")

    assert force_primary_var.get() is True
    assert db._can_fail_over() is False


async def test_failover_allowed_on_a_clean_read_only_session(db) -> None:
    await db.scalar(select(UserModel.id).limit(1))

    assert force_primary_var.get() is False
    assert db._can_fail_over() is True


async def test_pending_write_survives_a_replica_error(db, monkeypatch) -> None:
    """End to end: the write is still there after a failed read, not expunged."""
    email = make_email()
    db.add(UserModelFactory.build(email=email))

    real_scalar = AsyncSession.scalar
    attempts = {"n": 0}

    async def always_failing_scalar(self, statement, *args, **kwargs):
        attempts["n"] += 1
        raise _operational_error()

    monkeypatch.setattr(AsyncSession, "scalar", always_failing_scalar)

    with pytest.raises(OperationalError):
        await db.scalar(select(UserModel.id).limit(1))

    # The guard must have refused to retry — a retry implies a rollback,
    # and the rollback is what would have expunged the pending insert.
    assert attempts["n"] == 1, "failover must not retry while a write is pending"

    monkeypatch.setattr(AsyncSession, "scalar", real_scalar)

    await db.commit()
    found = await db.scalar(select(UserModel).where(UserModel.email == email))
    assert found is not None, "the pending write must not have been rolled away"


# ---------------------------------------------------------------------------
# Finding 4 — the before_flush listener pins ORM flushes
# ---------------------------------------------------------------------------


async def test_orm_flush_pins_request_to_primary(db) -> None:
    """A unit-of-work flush calls get_bind() with clause=None, so only the
    before_flush listener can set the sticky flag."""
    db.add(UserModelFactory.build())
    assert force_primary_var.get() is False

    await db.flush()

    assert force_primary_var.get() is True


# ---------------------------------------------------------------------------
# Finding 2 — the revocation check must not pin the rest of the request
# ---------------------------------------------------------------------------


async def test_exists_does_not_leak_primary_pin(db) -> None:
    repo = RevokedTokenRepository(db)

    assert await repo.exists(uuid.uuid4().hex) is False
    assert force_primary_var.get() is False, (
        "exists() must restore the flag — leaving it set pinned every "
        "authenticated request to primary and left the replica idle"
    )


async def test_exists_preserves_an_existing_pin(db) -> None:
    """reset() restores the previous value, not False."""
    repo = RevokedTokenRepository(db)
    force_primary_var.set(True)

    await repo.exists(uuid.uuid4().hex)

    assert force_primary_var.get() is True


async def test_exists_still_reads_from_primary(db, monkeypatch) -> None:
    """The pin must be active *during* the query — revocation reads must not
    be served by a lagging replica."""
    repo = RevokedTokenRepository(db)
    seen: list[bool] = []

    real_scalar = AsyncSession.scalar

    async def spy_scalar(self, statement, *args, **kwargs):
        seen.append(force_primary_var.get())
        return await real_scalar(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalar", spy_scalar)

    jti = uuid.uuid4().hex
    await repo.add(jti, datetime.now(UTC) + timedelta(hours=1))
    force_primary_var.set(False)
    seen.clear()
    assert await repo.exists(jti) is True

    assert seen == [True], "the revocation read itself must be pinned to primary"
