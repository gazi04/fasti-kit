import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from core.setting import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    query_cache_size=500,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=True,
    echo=settings.db_echo,
)
AsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)

sync_engine = engine.sync_engine


@event.listens_for(sync_engine, "checkout")
def receive_checkou(dbapi_connection, connection_record, connection_proxy):
    connection_record.info["checkout_start_time"] = time.time()

    pool = sync_engine.pool
    if pool.checkedout() >= settings.db_pool_size:
        logger.warning(
            f"Database pool is heavily utilized. Checked out: {pool.checkedout()}, "
            f"Size: {pool.size()}, Overflow: {pool.overflow()}"
        )


@event.listens_for(sync_engine, "checkin")
def receive_checkin(dbapi_connection, connection_record):
    start_time = connection_record.info.pop("checkout_start_time", None)
    if start_time:
        duration = time.time() - start_time
        if duration > 2.0:
            logger.warning(
                f"Connection leak detected! DB connection held fro {duration:.2f} seconds."
            )


class Base(AsyncAttrs, DeclarativeBase):
    pass


@asynccontextmanager
async def db_session() -> AsyncGenerator[AsyncSession]:
    db = AsyncSessionLocal()
    try:
        yield db
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with db_session() as db:
        yield db
