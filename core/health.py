import asyncio
import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from core.database import primary_engine, replica_engine
from core.queue import redis

logger = logging.getLogger(__name__)

health_router = APIRouter(prefix="/health", tags=["Health"])


async def _check_primary_database() -> None:
    async with primary_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_replica_database() -> None:
    async with replica_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    await redis.ping()


@health_router.get("/live", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, str]:
    """Lightweight process check returning 200 OK if server process is running."""
    return {"status": "ok"}


@health_router.get("/ready")
async def readiness(response: Response) -> dict:
    """Validates connectivity to Primary PostgreSQL, Replica PostgreSQL, and Redis."""
    results = await asyncio.gather(
        asyncio.wait_for(_check_primary_database(), timeout=2.0),
        asyncio.wait_for(_check_replica_database(), timeout=2.0),
        asyncio.wait_for(_check_redis(), timeout=2.0),
        return_exceptions=True,
    )

    checks = {}
    is_healthy = True

    for name, result in zip(
        ("database_primary", "database_replica", "redis"), results, strict=True
    ):
        if isinstance(result, Exception):
            logger.error(f"Readiness probe failed for {name}: {result}")
            checks[name] = f"unhealthy: {result}"
            is_healthy = False
        else:
            checks[name] = "ok"

    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "checks": checks}

    return {"status": "ok", "checks": checks}
