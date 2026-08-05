from redis.asyncio import Redis
from saq.queue.redis import RedisQueue

from core.setting import get_settings

settings = get_settings()

redis = Redis.from_url(
    settings.redis_url,
    socket_keepalive=True,
    socket_connect_timeout=5,
    health_check_interval=30,  # Fixed parameter name
)

task_queue = RedisQueue(redis)
