from unittest.mock import AsyncMock

from asgi_lifespan import LifespanManager
from sqlalchemy import text

import main
from core.database import dispose_engines, primary_engine, replica_engine
from core.redis import close_redis, redis


async def test_dispose_engines_is_idempotent() -> None:
    """dispose_engines() can run repeatedly; the engines stay usable afterwards
    (SQLAlchemy rebuilds the pool on the next connect)."""
    await dispose_engines()
    await dispose_engines()

    for engine in (primary_engine, replica_engine):
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT 1"))).scalar_one() == 1


async def test_close_redis_is_idempotent() -> None:
    """close_redis() can run repeatedly; redis-py reconnects on next use."""
    await close_redis()
    await close_redis()

    assert await redis.ping() is True


async def test_lifespan_shutdown_releases_resources(mocker) -> None:
    """Exiting the app lifespan disposes the DB engines and closes Redis exactly once."""
    dispose_spy = mocker.patch.object(main, "dispose_engines", new_callable=AsyncMock)
    redis_spy = mocker.patch.object(main, "close_redis", new_callable=AsyncMock)

    async with LifespanManager(main.app):
        dispose_spy.assert_not_awaited()

    dispose_spy.assert_awaited_once()
    redis_spy.assert_awaited_once()
