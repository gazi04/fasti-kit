import contextvars
import logging
import time

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from core.setting import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

bind_override_var: contextvars.ContextVar = contextvars.ContextVar(
    "bind_override", default=None
)


def create_engine(url: str) -> AsyncEngine:
    engine = create_async_engine(
        url,
        query_cache_size=500,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=True,
    )
    _attach_leak_listeners(engine.sync_engine)
    return engine


def _attach_leak_listeners(sync_engine) -> None:
    @event.listens_for(sync_engine, "checkout")
    def receive_checkout(dbapi_connection, connection_record, connection_proxy):
        connection_record.info["checkout_start_time"] = time.time()
        pool = sync_engine.pool
        if isinstance(pool, QueuePool) and pool.checkedout() >= settings.db_pool_size:
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
                    f"Connection leak! DB connection held for {duration:.2f} seconds."
                )


primary_engine = create_engine(settings.database_url)


class BindOverrideSession(Session):
    """Uses the connection in bind_override_var when a test has set one.

    This must live on the *sync* Session: AsyncSession proxies execution to
    a sync Session, and SQLAlchemy resolves binds there.
    """

    def get_bind(self, mapper=None, *, clause=None, bind=None, **kw):
        override = bind_override_var.get()
        if override is not None:
            return override
        return super().get_bind(mapper, clause=clause, bind=bind, **kw)
