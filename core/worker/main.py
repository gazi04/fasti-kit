# % if outbox
import asyncio
from contextlib import suppress

# % endif
from saq import CronJob

from core.database import dispose_engines

# % if outbox
from core.dead_letter.hook import record_dead_letter
from core.dead_letter.tasks import cleanup_dead_letter_task

# % endif
from core.logging.setup import setup_logging
from core.middlewares.correlation import request_id_context

# % if outbox
from core.outbox.relay import relay_loop
from core.outbox.tasks import cleanup_outbox_task

# % endif
from core.queue import task_queue
from core.redis import close_redis

from .tasks import (
    cleanup_refresh_sessions_task,
    cleanup_revoked_tokens_task,
    process_welcome_email,
    send_email_task,
)

setup_logging()


async def _bind_job_correlation_id(ctx) -> None:
    request_id_context.set(ctx["job"].key)


# % if outbox
async def _start_relay(ctx) -> None:
    ctx["outbox_relay"] = asyncio.create_task(relay_loop())


# % endif
async def _release_pools(ctx) -> None:
    # % if outbox
    relay = ctx.get("outbox_relay")
    if relay is not None:
        relay.cancel()
        with suppress(asyncio.CancelledError):
            await relay

    # % endif
    await dispose_engines()
    await close_redis()


settings = {
    "queue": task_queue,
    "functions": [process_welcome_email, send_email_task],
    "cron_jobs": [
        CronJob(cleanup_revoked_tokens_task, cron="0 3 * * *"),
        CronJob(cleanup_refresh_sessions_task, cron="15 3 * * *"),
        # % if outbox
        CronJob(cleanup_outbox_task, cron="30 3 * * *"),
        CronJob(cleanup_dead_letter_task, cron="0 4 * * *"),
        # % endif
    ],
    "concurrency": 10,
    "shutdown": _release_pools,
    "before_process": _bind_job_correlation_id,
    # % if outbox
    "startup": _start_relay,
    "after_process": record_dead_letter,
    # % endif
}
