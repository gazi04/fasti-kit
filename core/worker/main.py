import logging

from saq import CronJob

from core.database import dispose_engines
from core.queue import task_queue
from core.redis import close_redis

from .tasks import cleanup_revoked_tokens_task, process_welcome_email, send_email_task

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | WORKER | %(levelname)s | %(message)s",
    force=True,
)


async def _release_pools(ctx) -> None:
    """Drain the DB engine pools and the Redis client when the worker stops.

    The worker holds these because its tasks use AsyncSessionLocal / core.redis.
    """
    await dispose_engines()
    await close_redis()


# SAQ's Worker.__init__ folds every CronJob.function into its function registry
# automatically, so cron-only tasks (cleanup_revoked_tokens_task) are intentionally
# absent from "functions" — adding them there would just be a redundant duplicate.
settings = {
    "queue": task_queue,
    "functions": [process_welcome_email, send_email_task],
    "cron_jobs": [CronJob(cleanup_revoked_tokens_task, cron="0 3 * * *")],
    "concurrency": 10,
    "shutdown": _release_pools,
}
