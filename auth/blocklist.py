import logging
from collections.abc import Iterable
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from auth.entities.auth_session import TokenRef

logger = logging.getLogger(__name__)

JTI_KEY_PREFIX = "auth:blocklist:jti:"
READY_KEY = "auth:blocklist:ready"
SEEDING_KEY = "auth:blocklist:seeding"
SEEDING_LOCK_SECONDS = 60


class TokenBlocklist:
    def __init__(self, client: Redis) -> None:
        self._client = client

    async def revoke(self, tokens: Iterable[TokenRef]) -> None:
        now = datetime.now(UTC)
        async with self._client.pipeline(transaction=False) as pipe:
            queued = 0
            for token in tokens:
                ttl_ms = int((token.expires_at - now).total_seconds() * 1000)
                if ttl_ms > 0:
                    pipe.set(JTI_KEY_PREFIX + token.jti, 1, px=ttl_ms)
                    queued += 1
            if queued:
                await pipe.execute()

    async def lookup(self, jti: str) -> bool | None:
        try:
            revoked, ready = await self._client.mget(JTI_KEY_PREFIX + jti, READY_KEY)
        except RedisError:
            logger.warning("Token blocklist unavailable, falling back to the database")
            return None

        if ready is None:
            return None

        return revoked is not None

    async def claim_seeding(self) -> bool:
        try:
            return bool(
                await self._client.set(SEEDING_KEY, 1, nx=True, ex=SEEDING_LOCK_SECONDS)
            )
        except RedisError:
            return False

    async def seed(self, tokens: Iterable[TokenRef]) -> None:
        try:
            await self.revoke(tokens)
            await self._client.set(READY_KEY, 1)
        except RedisError:
            logger.warning("Token blocklist seeding failed", exc_info=True)
