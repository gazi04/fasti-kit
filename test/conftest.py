import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import core.models
from core.database import Base, get_db
from core.setting import get_settings
from main import app

settings = get_settings()
# Use a dedicated test database (e.g. localhost:5433 from docker-compose setup)
TEST_DATABASE_URL = settings.database_url.replace("fasti_kit", "fasti_kit_test")


@pytest.fixture(scope="session")
async def db_engine():
    """Session-scoped engine. Sets up schemas once for the entire test session."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    
    # Run migrations or drop/recreate all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
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
        bind=conn, 
        expire_on_commit=False,
        join_transaction_mode="create_savepoint"
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
