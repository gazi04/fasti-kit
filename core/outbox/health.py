from collections.abc import Awaitable

from fastapi import Depends

from core.outbox.dependencies import get_outbox_repository
from core.outbox.relay import RELAY_HEARTBEAT_KEY
from core.outbox.repository import OutboxRepository
from core.outbox.settings import get_outbox_settings
from core.redis import redis


async def check_relay_heartbeat() -> None:
    if not await redis.exists(RELAY_HEARTBEAT_KEY):
        raise RuntimeError("outbox relay heartbeat missing")


async def check_outbox_backlog(outbox: OutboxRepository) -> None:
    age = await outbox.oldest_pending_age()
    max_lag = get_outbox_settings().max_lag_seconds
    if age is not None and age > max_lag:
        raise RuntimeError(f"oldest pending outbox row is {age:.0f}s old")


async def outbox_checks(
    outbox: OutboxRepository = Depends(get_outbox_repository),
) -> dict[str, Awaitable[None]]:
    return {
        "outbox_relay": check_relay_heartbeat(),
        "outbox_backlog": check_outbox_backlog(outbox),
    }
