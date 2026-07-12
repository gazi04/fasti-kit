from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from core.setting import get_settings

settings = get_settings()
engine = create_async_engine(
    settings.database_url,
    query_cache_size=500,  # 500 is a default value
    pool_size=5,  # Maintains 5 persistent connections
    max_overflow=10,  # Can create 10 additional temporary connections
    pool_timeout=30,  # Wait 30 seconds for available connection
    pool_recycle=3600,  # Recycle connections after 1 hour
    pool_pre_ping=True,  # Test connection before using
    echo=True,
)
AsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(AsyncAttrs, DeclarativeBase):
    pass


@asynccontextmanager
async def db_session() -> AsyncGenerator[AsyncSession, None]:
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
