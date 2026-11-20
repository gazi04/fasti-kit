"""
Replica failover of the read_replica add-on (core/replica/routing.py).

- the failover must cover scalar() and get(), not only execute()
- the failover's rollback must never expunge pending, unflushed writes
- a session that already reads from the primary must not fail over
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.factories.user_factory import UserModelFactory, make_email
from core.replica import routing
from core.replica.routing import PINNED, STICKY, on_primary
from user.models import UserModel
from user.repositories.user_repository import UserRepository

FAKE_REPLICA = create_async_engine("postgresql+asyncpg://u:p@replica.invalid/app")


@pytest.fixture(autouse=True)
def fake_replica(monkeypatch):
    monkeypatch.setattr(routing, "replica_engine", FAKE_REPLICA)


def _operational_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("replica is down"))


async def test_scalar_fails_over_to_primary(db, monkeypatch) -> None:
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
    assert db.info[STICKY] is True, "the retry must stick to the primary"


async def test_a_refused_connection_fails_over_to_primary(db, monkeypatch) -> None:
    calls = {"n": 0}
    real_scalar = AsyncSession.scalar

    async def refused_once(self, statement, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionRefusedError(111, "Connection refused")
        return await real_scalar(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalar", refused_once)

    await db.scalar(select(UserModel.id).limit(1))

    assert calls["n"] == 2
    assert db.info[STICKY] is True


async def test_get_fails_over_to_primary(db, monkeypatch) -> None:
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
    assert db.info[STICKY] is True


async def test_failover_declines_while_pending_write_is_unflushed(db) -> None:
    """autoflush is off in the app, so db.add() leaves an instance pending
    with no flag set. Rolling back to retry would expunge it, the retry would
    succeed, and the eventual commit would write nothing."""
    email = make_email()
    db.add(UserModelFactory.build(email=email))

    assert not on_primary(db.sync_session), "no flush yet, so no flag yet"
    assert db._can_fail_over() is False, "pending write must veto failover"

    await db.commit()
    found = await db.scalar(select(UserModel).where(UserModel.email == email))
    assert found is not None


async def test_failover_declines_after_a_write(db) -> None:
    await UserRepository(db).add("Already Written", make_email(), "pw")

    assert db.info[STICKY] is True
    assert db._can_fail_over() is False


async def test_failover_declines_while_pinned(db) -> None:
    db.info[PINNED] = True

    assert db._can_fail_over() is False


async def test_failover_declines_without_a_replica(db, monkeypatch) -> None:
    monkeypatch.setattr(routing, "replica_engine", None)

    assert db._can_fail_over() is False


async def test_failover_allowed_on_a_clean_read_only_session(db) -> None:
    await db.scalar(select(UserModel.id).limit(1))

    assert not on_primary(db.sync_session)
    assert db._can_fail_over() is True


async def test_pending_write_survives_a_replica_error(db, monkeypatch) -> None:
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

    assert attempts["n"] == 1, "failover must not retry while a write is pending"

    monkeypatch.setattr(AsyncSession, "scalar", real_scalar)

    await db.commit()
    found = await db.scalar(select(UserModel).where(UserModel.email == email))
    assert found is not None, "the pending write must not have been rolled away"


async def test_orm_flush_sticks_to_primary(db) -> None:
    """A unit-of-work flush calls get_bind() with clause=None, so only the
    before_flush listener can set the sticky flag."""
    db.add(UserModelFactory.build())
    assert not on_primary(db.sync_session)

    await db.flush()

    assert db.info[STICKY] is True
