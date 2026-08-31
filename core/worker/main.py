import asyncio
import logging
from contextlib import suppress

from saq import CronJob

from core.database import dispose_engines
from core.dead_letter.hook import record_dead_letter
from core.outbox.relay import relay_loop
from core.queue import task_queue
from core.redis import close_redis

from .tasks import (
    cleanup_dead_letter_task,
    cleanup_outbox_task,
    cleanup_revoked_tokens_task,
    process_welcome_email,
    send_email_task,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | WORKER | %(levelname)s | %(message)s",
    force=True,
)


async def _start_relay(ctx) -> None:
    ctx["outbox_relay"] = asyncio.create_task(relay_loop())


async def _release_pools(ctx) -> None:
    relay = ctx.get("outbox_relay")
    if relay is not None:
        relay.cancel()
        with suppress(asyncio.CancelledError):
            await relay

    await dispose_engines()
    await close_redis()


settings = {
    "queue": task_queue,
    "functions": [process_welcome_email, send_email_task],
    "cron_jobs": [
        CronJob(cleanup_revoked_tokens_task, cron="0 3 * * *"),
        CronJob(cleanup_outbox_task, cron="30 3 * * *"),
        CronJob(cleanup_dead_letter_task, cron="0 4 * * *"),
    ],
    "concurrency": 10,
    "startup": _start_relay,
    "shutdown": _release_pools,
    "after_process": record_dead_letter,
}
