import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import Delete, Insert, Select, Update

from core.engine import BindOverrideSession, bind_override_var, create_engine
from core.replica.settings import get_replica_settings

logger = logging.getLogger(__name__)

STICKY = "replica_sticky_primary"
PINNED = "replica_pinned_primary"

WRITE_KEYWORDS = ("insert", "update", "delete", "create", "drop", "alter")


def _build_replica_engine() -> AsyncEngine | None:
    url = get_replica_settings().database_replica_url
    return create_engine(url) if url else None


replica_engine = _build_replica_engine()
replica_engines: dict[str, AsyncEngine] = (
    {} if replica_engine is None else {"replica": replica_engine}
)


def on_primary(session: Session) -> bool:
    return bool(session.info.get(STICKY) or session.info.get(PINNED))


def _is_write(clause) -> bool:
    if isinstance(clause, (Insert, Update, Delete)):
        return True
    text = getattr(clause, "text", None)
    return isinstance(text, str) and text.lstrip().lower().startswith(WRITE_KEYWORDS)


class RoutingSession(BindOverrideSession):
    """Sends plain SELECTs to the replica and everything else to the primary.

    A write marks the session sticky, so later reads in the same request see it.
    The mark is set before the test bind override is consulted, so tests that
    run on one connection still exercise it.
    """

    def get_bind(self, mapper=None, *, clause=None, bind=None, **kw):
        if _is_write(clause):
            self.info[STICKY] = True

        if (
            replica_engine is not None
            and bind_override_var.get() is None
            and not on_primary(self)
            and isinstance(clause, Select)
        ):
            return replica_engine.sync_engine

        return super().get_bind(mapper, clause=clause, bind=bind, **kw)


@event.listens_for(RoutingSession, "before_flush")
def _stick_on_flush(session, flush_context, instances) -> None:
    """A unit-of-work flush calls get_bind() with clause=None, so _is_write
    never sees it. Without this, a read after an ORM write could hit a
    lagging replica and miss the row it just wrote."""
    session.info[STICKY] = True


@contextmanager
def pin_to_primary(db: AsyncSession) -> Iterator[None]:
    previous = db.info.get(PINNED, False)
    db.info[PINNED] = True
    try:
        yield
    finally:
        db.info[PINNED] = previous


class AsyncResilientRoutingSession(AsyncSession):
    """Fails a replica read over to the primary, without ever trading away a write.

    asyncpg raises a refused or timed-out connect as a bare OSError, which
    SQLAlchemy does not wrap, so both error types count as "replica down".

    The failover wraps more than execute(): AsyncSession.scalar() and .get()
    call greenlet_spawn(self.sync_session.X, ...) directly and never dispatch
    through self.execute(). scalars() is not overridden — it delegates to
    self.execute() and would double-wrap the retry.
    """

    sync_session_class = RoutingSession

    def _can_fail_over(self) -> bool:
        """True only when the read went to the replica and a rollback destroys nothing.

        Retrying on the primary needs a rollback first, since Postgres refuses
        further work on an aborted transaction. The rollback is session-wide:
        - a sticky or pinned session read from the primary, so the failure was
          not the replica's;
        - new/dirty/deleted objects are unflushed work (autoflush is off), which
          the rollback would expunge, and the later commit would write nothing.
        Not `in_transaction()`: any read opens a transaction, so that would
        always refuse.
        """
        if replica_engine is None or on_primary(self.sync_session):
            return False

        sync = self.sync_session
        return not (sync.new or sync.dirty or sync.deleted)

    async def _with_failover(self, operation):
        try:
            return await operation()
        except (OperationalError, OSError) as e:
            if not self._can_fail_over():
                raise

            logger.warning(
                f"Replica DB connection failed. Falling back to Primary. Error: {e}"
            )
            self.info[STICKY] = True

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
