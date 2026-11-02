import asyncio
import logging
from contextlib import ExitStack

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from core.migration_lock import MIGRATION_LOCK_ID, migration_lock
from tests.conftest import TEST_DATABASE_URL

log = logging.getLogger("tests.migration_lock")


@pytest.fixture
async def lock_engine():
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
    yield engine
    await engine.dispose()


async def _try_lock(conn) -> bool:
    acquired = await conn.scalar(
        text("SELECT pg_try_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID}
    )
    if acquired:
        await conn.execute(
            text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRATION_LOCK_ID}
        )
    await conn.commit()
    return bool(acquired)


async def test_lock_is_exclusive_and_released_on_exit(lock_engine) -> None:
    async with lock_engine.connect() as holder, lock_engine.connect() as other:
        with ExitStack() as stack:
            await holder.run_sync(lambda c: stack.enter_context(migration_lock(c, log)))

            assert not holder.in_transaction()
            assert not await _try_lock(other)

            await holder.run_sync(lambda _: stack.close())

        assert await _try_lock(other)


async def test_second_caller_logs_and_waits_for_the_first(lock_engine, caplog) -> None:
    caplog.set_level(logging.INFO, logger=log.name)
    async with lock_engine.connect() as holder, lock_engine.connect() as waiter:
        await holder.execute(
            text("SELECT pg_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID}
        )
        await holder.commit()

        with ExitStack() as stack:
            entered = asyncio.create_task(
                waiter.run_sync(lambda c: stack.enter_context(migration_lock(c, log)))
            )
            await asyncio.sleep(0.2)

            assert not entered.done()
            assert "waiting" in caplog.text

            await holder.execute(
                text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRATION_LOCK_ID}
            )
            await holder.commit()
            await asyncio.wait_for(entered, timeout=5)

            assert not await _try_lock(holder)

            await waiter.run_sync(lambda _: stack.close())


async def test_lock_is_freed_with_the_connection_after_an_error(lock_engine) -> None:
    async with lock_engine.connect() as other:
        holder = await lock_engine.connect()

        def fail_while_locked(conn) -> None:
            with migration_lock(conn, log):
                raise RuntimeError("migration failed")

        with pytest.raises(RuntimeError, match="migration failed"):
            await holder.run_sync(fail_while_locked)

        assert not await _try_lock(other)

        await holder.close()

        assert await _try_lock(other)
