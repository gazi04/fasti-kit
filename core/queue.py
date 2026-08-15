from saq.queue.redis import RedisQueue

from core.redis import redis

task_queue = RedisQueue(redis)
