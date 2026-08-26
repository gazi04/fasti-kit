import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

import auth.dependencies as auth_dependencies
from core.database import (
    AsyncResilientRoutingSession,
    Base,
    bind_override_var,
    force_primary_var,
    get_db,
    primary_engine,
    replica_engine,
)
from core.redis import redis
from core.setting import get_settings
from main import app

settings = get_settings()
# Use a dedicated test database (e.g. localhost:5433 from docker-compose setup)
TEST_DATABASE_URL = settings.database_url.replace("fasti_kit", "fasti_kit_test")


@pytest.fixture(autouse=True)
async def _reset_redis_pool():
    """
    Dispose the shared Redis connection pool after every test.

    core/redis.py builds one module-level client at import time, and redis-py
    lazily binds its pool to whichever event loop first uses it. pytest-asyncio
    gives each test a fresh loop, so without this the second test to touch the
    cache reuses connections owned by a closed loop ("Event loop is closed").
    """
    yield
    await redis.aclose()


@pytest.fixture(autouse=True)
async def _reset_engine_pools():
    """Dispose the module-level engine pools after every test.

    core/database.py builds primary_engine/replica_engine at import time, and
    asyncpg binds each pooled connection to the event loop that created it.
    pytest-asyncio hands every test a fresh loop, so a connection left in a
    pool by one test fails pool_pre_ping in the next ("Event loop is closed").
    Same hazard, and same remedy, as _reset_redis_pool above.
    """
    yield
    await primary_engine.dispose()
    await replica_engine.dispose()


@pytest.fixture
async def db_engine():
    """
    Function-scoped engine.
    Sets up schemas once per test inside the same event loop.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture
async def db(db_engine):
    """
    Function-scoped session wrapping every test in a nested SAVEPOINT.
    Rolls back everything (even if application code calls commit()) at teardown.
    """
    # 1. Acquire an active connection from engine pool
    conn = await db_engine.connect()

    # 2. Begin parent transaction
    txn = await conn.begin()

    # 3. Instantiate the *real* application session class, bound to this
    # connection via the bind-override contextvar. Using a vanilla AsyncSession
    # here would bypass get_bind(), the before_flush primary-pinning listener
    # and the failover wrapper — the exact code Findings 3 and 4 live in.
    # join_transaction_mode="create_savepoint" maps commits/rollbacks to SAVEPOINTs.
    bind_token = bind_override_var.set(conn.sync_connection)
    force_token = force_primary_var.set(False)

    session = AsyncResilientRoutingSession(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )

    try:
        yield session
    finally:
        # 4. Clean up: close session, rollback outer transaction, free up connection.
        await session.close()
        await txn.rollback()
        await conn.close()
        force_primary_var.reset(force_token)
        bind_override_var.reset(bind_token)


class _NullCloseSession:
    """Hand the test session to `async with AsyncSessionLocal() as db` without
    letting the callback close it — the fixture owns that session's lifetime."""

    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info) -> bool:
        return False


@pytest.fixture
async def client(db, monkeypatch):
    """
    Function-scoped Async HTTP Client. Overrides get_db dependency.
    """

    # Inject our transactional session into application endpoints.
    # A plain `lambda: db` would skip db_session() entirely, leaving
    # force_primary_var unreset between requests; mirror its contract instead.
    async def _override_get_db():
        token = force_primary_var.set(False)
        try:
            yield db
        finally:
            force_primary_var.reset(token)

    app.dependency_overrides[get_db] = _override_get_db

    # is_token_revoked opens its own AsyncSessionLocal() against the *dev*
    # database, outside the fixture's savepoint. Point it at the test session
    # so authenticated routes can be exercised end to end.
    monkeypatch.setattr(
        auth_dependencies, "AsyncSessionLocal", lambda: _NullCloseSession(db)
    )

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def query_counter(db_engine):
    """
    Tracks the number of SQL queries executed during a single test.

    Usage:
        async def test_my_endpoint(client, query_counter):
            await client.get("/api/v1/user/list")
            assert query_counter["count"] <= 3
    """
    counter = {"count": 0}

    def _increment(*args, **kwargs) -> None:
        counter["count"] += 1

    event.listen(db_engine.sync_engine, "before_cursor_execute", _increment)
    yield counter
    event.remove(db_engine.sync_engine, "before_cursor_execute", _increment)
