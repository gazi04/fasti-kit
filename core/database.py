import contextvars
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import QueuePool
from sqlalchemy.sql.expression import Delete, Insert, Select, Update

from core.setting import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Context variable to track if a write occurred during the current HTTP request
force_primary_var: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "force_primary", default=False
)

bind_override_var: contextvars.ContextVar = contextvars.ContextVar(
    "bind_override", default=None
)


def create_engine(url: str):
    return create_async_engine(
        url,
        query_cache_size=500,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=True,
        echo=settings.db_echo,
    )


primary_engine = create_engine(settings.database_url)
replica_engine = create_engine(settings.get_replica_url)


# Attach connection leak listeners to both engines
def attach_pool_listeners(sync_engine):
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


attach_pool_listeners(primary_engine.sync_engine)
attach_pool_listeners(replica_engine.sync_engine)


class RoutingSession(Session):
    """Routes reads to the replica and writes to the primary.

    This must live on the *sync* Session: AsyncSession proxies execution to
    a sync Session, and SQLAlchemy resolves binds there — an override on the
    AsyncSession subclass is never consulted.
    """

    def get_bind(
        self,
        mapper=None,
        clause=None,
        bind=None,
        _sa_skip_events=None,
        _sa_skip_for_implicit_returning=False,
        **kw,
    ):
        """Intelligently routes queries and enforces 'sticky' primary connections."""

        # 0. Test escape hatch — bypass routing entirely when pinned to one bind
        override = bind_override_var.get()
        if override is not None:
            return override

        # 1. If a write previously occurred in this request, pin everything to primary
        if force_primary_var.get():
            return primary_engine.sync_engine

        # 2. Inspect the AST of the SQL clause
        if clause is not None:
            if isinstance(clause, (Insert, Update, Delete)):
                force_primary_var.set(True)
                return primary_engine.sync_engine

            if isinstance(clause, Select):
                return replica_engine.sync_engine

            if hasattr(clause, "text"):
                query_text = clause.text.lstrip().lower()
                if query_text.startswith(
                    ("insert", "update", "delete", "create", "drop", "alter")
                ):
                    force_primary_var.set(True)
                    return primary_engine.sync_engine

        # Default safety net
        return primary_engine.sync_engine


@event.listens_for(RoutingSession, "before_flush")
def _pin_primary_on_flush(session, flush_context, instances) -> None:
    """Pin the request to primary before an ORM flush emits its writes.

    get_bind() only sees an Insert/Update/Delete clause for Core-style
    statements. A unit-of-work flush calls it with `mapper` set and
    `clause=None`, which lands on the primary safety net but would never
    set the sticky flag — leaving a later read free to hit a lagging
    replica and miss the write it just made.
    """
    force_primary_var.set(True)


class AsyncResilientRoutingSession(AsyncSession):
    """Fails a replica read over to the primary, without ever trading away a write.

    The failover must wrap more than execute(): AsyncSession.scalar() and .get()
    call greenlet_spawn(self.sync_session.X, ...) directly and never dispatch
    through self.execute(), so an execute()-only override misses every read this
    codebase actually performs. scalars() is deliberately NOT overridden — it
    delegates to self.execute() and would double-wrap the retry.
    """

    sync_session_class = RoutingSession

    def _can_fail_over(self) -> bool:
        """True only when a rollback would destroy nothing.

        Retrying on the primary requires rolling back the failed transaction
        first — Postgres refuses further work on an aborted one. That rollback
        is transaction-wide, so it is only safe while the session holds no work:

        - force_primary_var means a write already routed to primary (set by the
          repositories, by get_bind() on Insert/Update/Delete, and by the
          before_flush listener). A replica read cannot have been the failure.
        - new/dirty/deleted means pending, *unflushed* ORM work. autoflush is
          off, so `db.add(model)` sits pending with no flag set; rolling back
          would expunge it, the retry would succeed, and the later commit()
          would write nothing while the route returned 200.

        NOT `self.in_transaction()`: SQLAlchemy opens a transaction on the first
        read too, so that is True after any query and would disable failover.
        """
        if force_primary_var.get():
            return False

        sync = self.sync_session
        return not (sync.new or sync.dirty or sync.deleted)

    async def _with_failover(self, operation):
        try:
            return await operation()
        except OperationalError as e:
            if not self._can_fail_over():
                raise

            logger.warning(
                f"Replica DB connection failed. Falling back to Primary. Error: {e}"
            )
            force_primary_var.set(True)

            await self.rollback()
            return await operation()

    async def execute(self, statement, *args, **kwargs):
        return await self._with_failover(
            lambda: AsyncSession.execute(self, statement, *args, **kwargs)
        )

    async def scalar(self, statement, *args, **kwargs):
        return await self._with_failover(
            lambda: AsyncSession.scalar(self, statement, *args, **kwargs)
        )

    async def get(self, entity, ident, *args, **kwargs):
        return await self._with_failover(
            lambda: AsyncSession.get(self, entity, ident, *args, **kwargs)
        )


AsyncSessionLocal = async_sessionmaker(
    class_=AsyncResilientRoutingSession,
    sync_session_class=RoutingSession,
    autocommit=False,
    autoflush=False,
)


class Base(AsyncAttrs, DeclarativeBase):
    pass


@asynccontextmanager
async def db_session() -> AsyncGenerator[AsyncSession]:
    # Reset the context variable at the start of every session/request
    token = force_primary_var.set(False)
    db = AsyncSessionLocal()
    try:
        yield db
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
        force_primary_var.reset(token)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with db_session() as db:
        yield db
