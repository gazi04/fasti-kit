import asyncio
import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from core.database import engine
from core.queue import redis

logger = logging.getLogger(__name__)

health_router = APIRouter(prefix="/health", tags=["Health"])


async def _check_database() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    await redis.ping()


@health_router.get("/live", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, str]:
    """Lightweight process check returning 200 OK if server process is running."""
    return {"status": "ok"}


@health_router.get("/ready")
async def readiness(response: Response) -> dict:
    """Validates connectivity to PostgreSQL and Redis with short timeouts."""
    checks = {}
    is_healthy = True

    try:
        await asyncio.wait_for(_check_database(), timeout=2.0)
        checks["database"] = "ok"
    except Exception as err:
        logger.error(f"Readiness probe failed for database: {err}")
        checks["database"] = f"unhealthy: {err}"
        is_healthy = False

    try:
        await asyncio.wait_for(_check_redis(), timeout=2.0)
        checks["redis"] = "ok"
    except Exception as err:
        logger.error(f"Readiness probe failed for redis: {err}")
        checks["redis"] = f"unhealthy: {err}"
        is_healthy = False

    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "checks": checks}

    return {"status": "ok", "checks": checks}
