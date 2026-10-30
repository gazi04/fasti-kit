"""
Tests for the @cache decorator and invalidate_tags in core/cache.py.

Runs against the real Redis like the rest of the suite. Every test caches
under its own uuid tag and arguments, and invalidates that tag at the end,
so runs never see each other's entries.
"""

from dataclasses import dataclass
from uuid import uuid4

import pytest

from core.cache import cache, invalidate_tags
from core.redis import redis
from core.setting import get_settings


@dataclass
class Item:
    key: str
    calls: int


@pytest.fixture
async def tag():
    tag = f"test-{uuid4()}"
    yield tag
    await invalidate_tags(tag)


def _counted(tag: str):
    calls = {"count": 0}

    @cache(ttl=60, tags=[tag])
    async def load(key: str) -> Item:
        calls["count"] += 1
        return Item(key=key, calls=calls["count"])

    return load, calls


async def test_second_call_is_served_from_redis(tag) -> None:
    load, calls = _counted(tag)
    key = str(uuid4())

    first = await load(key)
    second = await load(key)

    assert calls["count"] == 1
    assert second == first == Item(key=key, calls=1)


async def test_cached_entry_expires_after_ttl(tag) -> None:
    load, _ = _counted(tag)
    await load(str(uuid4()))

    [cache_key] = await redis.smembers(f"{get_settings().cache_prefix}:tags:{tag}")

    assert 0 < await redis.ttl(cache_key) <= 60


async def test_different_arguments_are_cached_separately(tag) -> None:
    load, calls = _counted(tag)

    await load(str(uuid4()))
    await load(str(uuid4()))

    assert calls["count"] == 2


async def test_invalidate_tags_forces_a_recompute(tag) -> None:
    load, calls = _counted(tag)
    key = str(uuid4())

    await load(key)
    await invalidate_tags(tag)
    after = await load(key)

    assert calls["count"] == 2
    assert after.calls == 2


async def test_self_is_left_out_of_the_cache_key(tag) -> None:
    calls = {"count": 0}

    class Service:
        @cache(ttl=60, tags=[tag])
        async def load(self, key: str) -> Item:
            calls["count"] += 1
            return Item(key=key, calls=calls["count"])

    key = str(uuid4())
    await Service().load(key)
    await Service().load(key)

    assert calls["count"] == 1


def test_missing_return_annotation_is_rejected() -> None:
    with pytest.raises(ValueError, match="return type annotation"):

        @cache(ttl=60)
        async def load(key: str):
            return key
