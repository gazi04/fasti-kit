import uuid
from datetime import UTC, datetime, timedelta

import pytest
from authx import TokenPayload
from redis.exceptions import ConnectionError as RedisConnectionError

import auth.dependencies as auth_dependencies
from auth.blocklist import JTI_KEY_PREFIX, READY_KEY, SEEDING_KEY, TokenBlocklist
from auth.dependencies import auth, blocklist, is_token_revoked
from auth.entities.auth_session import TokenRef
from auth.repositories.revoked_token_repository import RevokedTokenRepository
from core.factories.user_factory import make_email
from core.redis import redis
from core.setting import get_settings
from user.repositories.user_repository import UserRepository


def _ref(minutes: int = 15) -> TokenRef:
    return TokenRef(uuid.uuid4().hex, datetime.now(UTC) + timedelta(minutes=minutes))


def _token(user_id: uuid.UUID) -> str:
    return auth.create_access_token(uid=str(user_id))


def _ref_of(token: str) -> TokenRef:
    settings = get_settings()
    payload = TokenPayload.decode(
        token,
        key=settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        verify=True,
    )
    assert payload.jti is not None
    return TokenRef(payload.jti, payload.expiry_datetime)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def session_opens(monkeypatch):
    opened = {"count": 0}
    original = auth_dependencies.AsyncSessionLocal

    def _counting():
        opened["count"] += 1
        return original()

    monkeypatch.setattr(auth_dependencies, "AsyncSessionLocal", _counting)
    return opened


async def test_revoke_stores_the_jti_with_the_token_lifetime() -> None:
    ref = _ref(minutes=15)

    await blocklist.revoke([ref])

    ttl_ms = await redis.pttl(JTI_KEY_PREFIX + ref.jti)
    assert 14 * 60 * 1000 < ttl_ms <= 15 * 60 * 1000


async def test_revoke_skips_a_token_that_already_expired() -> None:
    ref = _ref(minutes=-1)

    await blocklist.revoke([ref])

    assert await redis.exists(JTI_KEY_PREFIX + ref.jti) == 0


async def test_lookup_distinguishes_revoked_clean_and_unknown() -> None:
    ref = _ref()
    await blocklist.revoke([ref])

    assert await blocklist.lookup(ref.jti) is True
    assert await blocklist.lookup(uuid.uuid4().hex) is False

    await redis.delete(READY_KEY)
    assert await blocklist.lookup(ref.jti) is None


async def test_lookup_returns_none_when_redis_is_down(monkeypatch) -> None:
    async def _down(*args, **kwargs):
        raise RedisConnectionError("down")

    monkeypatch.setattr(redis, "mget", _down)

    assert await blocklist.lookup(uuid.uuid4().hex) is None


async def test_clean_token_check_opens_no_database_session(db, session_opens) -> None:
    token = _token(uuid.uuid4())

    assert await is_token_revoked(token) is False
    assert session_opens["count"] == 0


async def test_revoked_token_check_opens_no_database_session(db, session_opens) -> None:
    token = _token(uuid.uuid4())
    await blocklist.revoke([_ref_of(token)])

    assert await is_token_revoked(token) is True
    assert session_opens["count"] == 0


async def test_logout_blocks_the_access_token_through_redis(client, db) -> None:
    user = await UserRepository(db).add("Blocked", make_email(), "pw")
    token = _token(user.id)
    ref = _ref_of(token)

    logout = await client.post("/api/v1/auth/logout", headers=_bearer(token))
    assert logout.status_code == 200, logout.text

    assert await redis.exists(JTI_KEY_PREFIX + ref.jti) == 1
    again = await client.post("/api/v1/auth/logout", headers=_bearer(token))
    assert again.status_code in (401, 403, 422)


async def test_database_still_rejects_when_redis_is_down(db, monkeypatch) -> None:
    token = _token(uuid.uuid4())
    ref = _ref_of(token)
    await RevokedTokenRepository(db).add(ref.jti, ref.expires_at)

    async def _down(*args, **kwargs):
        raise RedisConnectionError("down")

    monkeypatch.setattr(redis, "mget", _down)
    monkeypatch.setattr(redis, "set", _down)

    assert await is_token_revoked(token) is True


async def test_missing_ready_key_falls_back_to_the_database_and_reseeds(db) -> None:
    token = _token(uuid.uuid4())
    ref = _ref_of(token)
    await RevokedTokenRepository(db).add(ref.jti, ref.expires_at)
    await redis.delete(READY_KEY)

    assert await is_token_revoked(token) is True

    assert await redis.exists(READY_KEY) == 1
    assert await redis.exists(JTI_KEY_PREFIX + ref.jti) == 1


async def test_only_one_caller_wins_the_seeding_lock() -> None:
    first = await blocklist.claim_seeding()
    second = await blocklist.claim_seeding()

    assert (first, second) == (True, False)
    assert await redis.exists(SEEDING_KEY) == 1


async def test_revoke_failure_propagates(monkeypatch) -> None:
    broken = TokenBlocklist(redis)

    async def _down(*args, **kwargs):
        raise RedisConnectionError("down")

    monkeypatch.setattr(redis, "pipeline", lambda *a, **k: _FailingPipeline())

    with pytest.raises(RedisConnectionError):
        await broken.revoke([_ref()])


class _FailingPipeline:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def set(self, *args, **kwargs):
        return self

    async def execute(self):
        raise RedisConnectionError("down")
