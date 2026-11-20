import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractContextManager, asynccontextmanager, nullcontext

from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase

from core.engine import BindOverrideSession, primary_engine

# % if read_replica
from core.replica.routing import (
    AsyncResilientRoutingSession,
    pin_to_primary,
    replica_engines,
)

# % endif

logger = logging.getLogger(__name__)


class AppSession(AsyncSession):
    sync_session_class = BindOverrideSession


def _one_database(db: AsyncSession) -> AbstractContextManager[None]:
    return nullcontext()


engines: dict[str, AsyncEngine] = {"primary": primary_engine}
session_class: type[AsyncSession] = AppSession
use_primary: Callable[[AsyncSession], AbstractContextManager[None]] = _one_database
# % if read_replica
engines.update(replica_engines)
session_class = AsyncResilientRoutingSession
use_primary = pin_to_primary
# % endif

AsyncSessionLocal = async_sessionmaker(
    primary_engine,
    class_=session_class,
    autocommit=False,
    autoflush=False,
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


AFTER_COMMIT_KEY = "after_commit"


def after_commit(db: AsyncSession, callback: Callable[[], Awaitable[object]]) -> None:
    db.info.setdefault(AFTER_COMMIT_KEY, []).append(callback)


@asynccontextmanager
async def transaction(db: AsyncSession) -> AsyncGenerator[None]:
    try:
        with use_primary(db):
            yield
            callbacks = db.info.pop(AFTER_COMMIT_KEY, [])
            await db.commit()
    except Exception:
        db.info.pop(AFTER_COMMIT_KEY, None)
        await db.rollback()
        raise

    for callback in callbacks:
        try:
            await callback()
        except Exception:
            logger.exception("After-commit callback failed; its work was not done")


async def dispose_engines() -> None:
    """Close every engine's connection pool.

    Idempotent — SQLAlchemy lazily rebuilds a fresh pool on the next connect,
    so this is safe to call more than once. Called from the app lifespan
    shutdown, the SAQ worker's shutdown hook and the test teardown.
    """
    for engine in engines.values():
        await engine.dispose()
