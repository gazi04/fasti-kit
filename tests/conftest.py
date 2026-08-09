import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.database import Base, get_db
from core.setting import get_settings
from main import app

settings = get_settings()
# Use a dedicated test database (e.g. localhost:5433 from docker-compose setup)
TEST_DATABASE_URL = settings.database_url.replace("fasti_kit", "fasti_kit_test")


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

    # 3. Instantiate session bound to this connection.
    # We turn on join_transaction_mode="create_savepoint" to map commits/rollbacks
    # to SAVEPOINTs.
    session = AsyncSession(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )

    try:
        yield session
    finally:
        # 4. Clean up: close session, rollback outer transaction, free up connection.
        await session.close()
        await txn.rollback()
        await conn.close()


@pytest.fixture
async def client(db):
    """
    Function-scoped Async HTTP Client. Overrides get_db dependency.
    """
    # Inject our transactional session into application endpoints
    app.dependency_overrides[get_db] = lambda: db
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
            await client.get("/api/users/me")
            assert query_counter["count"] <= 3
    """
    counter = {"count": 0}

    def _increment(*args, **kwargs) -> None:
        counter["count"] += 1

    event.listen(db_engine.sync_engine, "before_cursor_execute", _increment)
    yield counter
    event.remove(db_engine.sync_engine, "before_cursor_execute", _increment)
