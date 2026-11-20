import asyncio
import logging
from collections.abc import Awaitable, Mapping

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from core.database import engines

# % if outbox
from core.outbox.health import outbox_checks

# % endif
from core.queue import redis, task_queue

logger = logging.getLogger(__name__)

health_router = APIRouter(prefix="/health", tags=["Health"])

CHECK_TIMEOUT = 2.0


async def _check_database(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    await redis.ping()


async def _check_worker() -> None:
    info = await task_queue.info()
    if not info["workers"]:
        raise RuntimeError("no active SAQ worker")


async def _no_extra_checks() -> dict[str, Awaitable[None]]:
    return {}


worker_checks = _no_extra_checks
# % if outbox
worker_checks = outbox_checks
# % endif


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
    """Validates connectivity to every database engine and to Redis."""
    return await _run_checks(
        {
            **{
                f"database_{name}": _check_database(engine)
                for name, engine in engines.items()
            },
            "redis": _check_redis(),
        },
        response,
    )


@health_router.get("/workers")
async def workers(
    response: Response,
    extra_checks: Mapping[str, Awaitable[None]] = Depends(worker_checks),
) -> dict:
    """Validates the SAQ worker is up, plus any add-on's background checks.

    Kept apart from /ready so a dead worker does not pull API instances out of rotation.
    """
    return await _run_checks(
        {
            "worker": _check_worker(),
            **extra_checks,
        },
        response,
    )
