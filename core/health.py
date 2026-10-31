import asyncio
import logging
from collections.abc import Awaitable, Mapping

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text

from core.database import primary_engine, replica_engine
from core.outbox.dependencies import get_outbox_repository
from core.outbox.relay import RELAY_HEARTBEAT_KEY
from core.outbox.repository import OutboxRepository
from core.queue import redis, task_queue
from core.setting import get_settings

logger = logging.getLogger(__name__)

health_router = APIRouter(prefix="/health", tags=["Health"])

CHECK_TIMEOUT = 2.0


async def _check_primary_database() -> None:
    async with primary_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_replica_database() -> None:
    async with replica_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    await redis.ping()


async def _check_worker() -> None:
    info = await task_queue.info()
    if not info["workers"]:
        raise RuntimeError("no active SAQ worker")


async def _check_relay_heartbeat() -> None:
    if not await redis.exists(RELAY_HEARTBEAT_KEY):
        raise RuntimeError("outbox relay heartbeat missing")


async def _check_outbox_backlog(outbox: OutboxRepository) -> None:
    age = await outbox.oldest_pending_age()
    max_lag = get_settings().outbox_max_lag_seconds
    if age is not None and age > max_lag:
        raise RuntimeError(f"oldest pending outbox row is {age:.0f}s old")


async def _run_checks(
    checks: Mapping[str, Awaitable[None]], response: Response
) -> dict:
    results = await asyncio.gather(
        *(asyncio.wait_for(check, timeout=CHECK_TIMEOUT) for check in checks.values()),
        return_exceptions=True,
    )

    report = {}
    is_healthy = True

    for name, result in zip(checks, results, strict=True):
        if isinstance(result, BaseException):
            detail = str(result) or type(result).__name__
            logger.error(f"Health probe failed for {name}: {detail}")
            report[name] = f"unhealthy: {detail}"
            is_healthy = False
        else:
            report[name] = "ok"

    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "checks": report}

    return {"status": "ok", "checks": report}


@health_router.get("/live", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, str]:
    """Lightweight process check returning 200 OK if server process is running."""
    return {"status": "ok"}


@health_router.get("/ready")
async def readiness(response: Response) -> dict:
    """Validates connectivity to Primary PostgreSQL, Replica PostgreSQL, and Redis."""
    return await _run_checks(
        {
            "database_primary": _check_primary_database(),
            "database_replica": _check_replica_database(),
            "redis": _check_redis(),
        },
        response,
    )


@health_router.get("/workers")
async def workers(
    response: Response,
    outbox: OutboxRepository = Depends(get_outbox_repository),
) -> dict:
    """Validates the SAQ worker is up and the outbox relay is alive and keeping up.

    Kept apart from /ready so a dead worker does not pull API instances out of rotation.
    """
    return await _run_checks(
        {
            "worker": _check_worker(),
            "outbox_relay": _check_relay_heartbeat(),
            "outbox_backlog": _check_outbox_backlog(outbox),
        },
        response,
    )
