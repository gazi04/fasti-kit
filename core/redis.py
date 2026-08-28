from redis.asyncio import Redis

from core.setting import get_settings

settings = get_settings()

redis = Redis.from_url(
    settings.redis_url,
    socket_keepalive=True,
    socket_connect_timeout=5,
    health_check_interval=30,  # Fixed parameter name
)


async def close_redis() -> None:
    """Close the shared async Redis client.

    Also covers the SAQ task_queue transport (core/queue.py), which wraps this
    same client. Idempotent — redis-py reconnects on next use. Called from the
    app lifespan shutdown and the SAQ worker's shutdown hook.
    """
    await redis.aclose()
