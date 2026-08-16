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
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import QueuePool
from sqlalchemy.sql.expression import Delete, Insert, Select, Update

from core.setting import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Context variable to track if a write occurred during the current HTTP request
force_primary_var: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "force_primary", default=False
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
                logger.warning(f"Connection leak! DB connection held for {duration:.2f} seconds.")

attach_pool_listeners(primary_engine.sync_engine)
attach_pool_listeners(replica_engine.sync_engine)


class AsyncResilientRoutingSession(AsyncSession):
    def get_bind(self, mapper=None, clause=None, bind=None, _sa_skip_events=None, _sa_skip_for_implicit_returning=False, **kw):
        """Intelligently routes queries and enforces 'sticky' primary connections."""
        
        # 1. If we are flushing (writing) or a write previously occurred in this request
        if self._flushing or force_primary_var.get():
            return primary_engine.sync_engine
            
        # 2. Inspect the AST of the SQL clause
        if clause is not None:
            # Sticky pinning: If it's a mutating query, flag the request to only use Primary
            if isinstance(clause, (Insert, Update, Delete)):
                force_primary_var.set(True)
                return primary_engine.sync_engine
                
            # If it is a pure read, use the Replica
            if isinstance(clause, Select):
                return replica_engine.sync_engine
                
            # Raw SQL text inspection fallback
            if hasattr(clause, "text"):
                query_text = clause.text.lstrip().lower()
                if query_text.startswith(("insert", "update", "delete", "create", "drop", "alter")):
                    force_primary_var.set(True)
                    return primary_engine.sync_engine
                    
        # Default safety net
        return primary_engine.sync_engine

    async def execute(self, statement, *args, **kwargs):
        """Catches Replica connection errors and automatically fails over to Primary."""
        try:
            return await super().execute(statement, *args, **kwargs)
        except OperationalError as e:
            # If we were querying the replica and it failed, failover to primary
            if not force_primary_var.get():
                logger.warning(f"Replica DB connection failed. Falling back to Primary. Error: {e}")
                force_primary_var.set(True)
                
                # Rollback the broken replica transaction state and retry the query on primary
                await self.rollback()
                return await super().execute(statement, *args, **kwargs)
            raise


AsyncSessionLocal = async_sessionmaker(
    class_=AsyncResilientRoutingSession, 
    autocommit=False, 
    autoflush=False
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
