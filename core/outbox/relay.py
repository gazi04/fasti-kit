import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from core.outbox.repository import OutboxRepository
from core.queue import enqueue_task
from core.redis import redis
from core.setting import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

RELAY_HEARTBEAT_KEY = "outbox:relay:heartbeat"
RELAY_HEARTBEAT_TTL = max(30, int(6 * settings.outbox_poll_interval))


async def _enqueue(task_name: str, key: str, payload: dict[str, Any]) -> None:
    await enqueue_task(task_name, key=key, **payload)


async def dispatch_pending(db: AsyncSession, *, batch_size: int) -> tuple[int, int]:
    return await OutboxRepository(db).dispatch_pending(
        batch_size, max_attempts=settings.outbox_max_attempts, send=_enqueue
    )


def _log_relay_failure(error: Exception, failures_in_a_row: int) -> None:
    if failures_in_a_row == 1:
        logger.exception("Outbox relay iteration failed; retrying")
        return

    first_line = next(iter(str(error).splitlines()), "")
    logger.warning(
        "Outbox relay still failing (%d in a row): %s: %s",
        failures_in_a_row,
        type(error).__name__,
        first_line,
    )


async def relay_loop() -> None:
    failures_in_a_row = 0

    while True:
        try:
            async with AsyncSessionLocal() as db:
                dispatched, failed = await dispatch_pending(
                    db, batch_size=settings.outbox_batch_size
                )
            await redis.set(RELAY_HEARTBEAT_KEY, "1", ex=RELAY_HEARTBEAT_TTL)
        except Exception as error:
            failures_in_a_row += 1
            _log_relay_failure(error, failures_in_a_row)
        else:
            if failures_in_a_row:
                logger.info(
                    "Outbox relay recovered after %d failed iterations",
                    failures_in_a_row,
                )
                failures_in_a_row = 0
            if dispatched or failed:
                logger.info("Outbox relay: dispatched=%d failed=%d", dispatched, failed)

        await asyncio.sleep(settings.outbox_poll_interval)
