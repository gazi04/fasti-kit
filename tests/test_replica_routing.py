"""
Routing decisions of the read_replica add-on (core/replica/routing.py).

The class under test is the *sync* RoutingSession: SQLAlchemy resolves binds
through the sync Session that AsyncSession proxies to. get_bind() only
returns an engine reference and never connects, so a fake replica engine at
an unreachable host is enough to tell the two binds apart.
"""

import pytest
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.ext.asyncio import create_async_engine

from auth.repositories.revoked_token_repository import RevokedTokenRepository
from core.database import primary_engine, transaction, use_primary
from core.factories.user_factory import make_email
from core.replica import routing
from core.replica.routing import PINNED, STICKY, RoutingSession, on_primary
from core.replica.settings import ReplicaSettings
from user.models import UserModel
from user.repositories.user_repository import UserRepository

FAKE_REPLICA = create_async_engine("postgresql+asyncpg://u:p@replica.invalid/app")


@pytest.fixture(autouse=True)
def fake_replica(monkeypatch):
    monkeypatch.setattr(routing, "replica_engine", FAKE_REPLICA)


def _session() -> RoutingSession:
    return RoutingSession(bind=primary_engine.sync_engine)


PRIMARY = primary_engine.sync_engine
REPLICA = FAKE_REPLICA.sync_engine


def test_select_routes_to_replica() -> None:
    assert _session().get_bind(clause=select(UserModel)) is REPLICA


@pytest.mark.parametrize(
    "clause",
    [
        insert(UserModel),
        update(UserModel),
        delete(UserModel),
        text("UPDATE users SET is_active = false"),
    ],
)
def test_write_routes_to_primary_and_sticks(clause) -> None:
    session = _session()

    assert session.get_bind(clause=clause) is PRIMARY
    assert session.info[STICKY] is True
    assert session.get_bind(clause=select(UserModel)) is PRIMARY


def test_raw_text_select_falls_back_to_primary() -> None:
    session = _session()

    assert session.get_bind(clause=text("SELECT 1")) is PRIMARY
    assert not on_primary(session)


def test_no_clause_falls_back_to_primary() -> None:
    assert _session().get_bind(clause=None) is PRIMARY


def test_pinned_session_reads_from_primary() -> None:
    session = _session()
    session.info[PINNED] = True

    assert session.get_bind(clause=select(UserModel)) is PRIMARY


def test_without_a_replica_everything_goes_to_primary(monkeypatch) -> None:
    monkeypatch.setattr(routing, "replica_engine", None)

    assert _session().get_bind(clause=select(UserModel)) is PRIMARY


def test_sessions_do_not_share_the_sticky_flag() -> None:
    writer, reader = _session(), _session()
    writer.get_bind(clause=insert(UserModel))

    assert reader.get_bind(clause=select(UserModel)) is REPLICA


def test_unset_url_builds_no_replica_engine(monkeypatch) -> None:
    monkeypatch.setattr(
        routing,
        "get_replica_settings",
        lambda: ReplicaSettings.model_construct(database_replica_url=None),
    )

    assert routing._build_replica_engine() is None


def test_empty_url_builds_no_replica_engine(monkeypatch) -> None:
    monkeypatch.setattr(
        routing,
        "get_replica_settings",
        lambda: ReplicaSettings.model_construct(database_replica_url=""),
    )

    assert routing._build_replica_engine() is None


async def test_use_primary_pins_and_restores(db) -> None:
    with use_primary(db):
        assert db.info[PINNED] is True
        with use_primary(db):
            pass
        assert db.info[PINNED] is True

    assert db.info[PINNED] is False


async def test_a_write_inside_use_primary_stays_sticky(db) -> None:
    with use_primary(db):
        await UserRepository(db).stage_add("Sticky", make_email(), "pw")

    assert db.info[STICKY] is True


async def test_a_core_write_under_the_test_bind_sets_sticky(db) -> None:
    await db.execute(
        update(UserModel).where(UserModel.email == make_email()).values(is_active=False)
    )

    assert db.info[STICKY] is True


async def test_transaction_pins_its_reads(db, monkeypatch) -> None:
    seen: list[bool] = []
    real_get_bind = RoutingSession.get_bind

    def spy(self, mapper=None, *, clause=None, bind=None, **kw):
        seen.append(on_primary(self))
        return real_get_bind(self, mapper, clause=clause, bind=bind, **kw)

    monkeypatch.setattr(RoutingSession, "get_bind", spy)

    async with transaction(db):
        await db.scalar(select(UserModel.id).limit(1))

    assert seen == [True]


async def test_a_read_only_transaction_is_not_sticky(db) -> None:
    await UserRepository(db).get_by_email(make_email(), consistent=True)

    assert not on_primary(db.sync_session)


async def test_revocation_check_reads_primary_without_pinning_the_session(
    db, monkeypatch
) -> None:
    seen: list[bool] = []
    real_get_bind = RoutingSession.get_bind

    def spy(self, mapper=None, *, clause=None, bind=None, **kw):
        seen.append(on_primary(self))
        return real_get_bind(self, mapper, clause=clause, bind=bind, **kw)

    monkeypatch.setattr(RoutingSession, "get_bind", spy)

    assert await RevokedTokenRepository(db).exists("unknown-jti") is False

    assert seen == [True], "the revocation read must hit the primary"
    assert not on_primary(db.sync_session), "and must not pin the rest of the request"


def test_replica_url_reads_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_REPLICA_URL", "postgresql+asyncpg://u:p@r:6000/app")

    assert (
        ReplicaSettings().database_replica_url == "postgresql+asyncpg://u:p@r:6000/app"
    )
