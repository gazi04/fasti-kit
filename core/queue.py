from typing import Any

from saq import Job
from saq.queue.redis import RedisQueue

from core.redis import redis
from core.setting import get_settings

task_queue = RedisQueue(redis)
_settings = get_settings()


async def enqueue_task(task_name: str, *, key: str, **kwargs: Any) -> Job | None:
    """Enqueue a task with the project-wide retry policy applied.

    SAQ jobs default to ``retries=1``, which — because ``attempts`` reaches 1 on
    the first run — means a job never actually retries. Route every enqueue
    through here so a transient failure is retried with backoff before the job
    is dead-lettered.
    """
    return await task_queue.enqueue(
        task_name,
        key=key,
        retries=_settings.task_max_retries,
        retry_delay=_settings.task_retry_delay,
        retry_backoff=_settings.task_retry_backoff,
        **kwargs,
    )
