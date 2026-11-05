import secrets

import pytest
from sqlalchemy.engine import URL, make_url

from core.database import primary_engine, replica_engine
from core.redis import redis
from core.setting import get_settings
from tests.isolation_plugin import _test_database_url, _test_redis_db

RANDOM_PASSWORD = secrets.token_hex(8)
DEV_URL = URL.create(
    "postgresql+asyncpg",
    username="user",
    password=RANDOM_PASSWORD,
    host="localhost",
    port=5433,
    database="app",
).render_as_string(hide_password=False)


def test_derives_the_test_database_and_keeps_the_password() -> None:
    derived = make_url(_test_database_url(DEV_URL))

    assert derived.database == "app_test"
    assert derived.password == RANDOM_PASSWORD


def test_derivation_is_idempotent() -> None:
    once = _test_database_url(DEV_URL)

    assert _test_database_url(once) == once


def test_refuses_a_url_without_a_database() -> None:
    with pytest.raises(pytest.UsageError):
        _test_database_url("postgresql+asyncpg://localhost:5433")


def test_refuses_a_test_redis_db_equal_to_the_dev_one(monkeypatch) -> None:
    monkeypatch.setenv("TEST_REDIS_DB", "3")

    with pytest.raises(pytest.UsageError, match="dev REDIS_DB"):
        _test_redis_db(dev_redis_db=3)


def test_the_app_under_test_points_at_the_test_database() -> None:
    assert (primary_engine.url.database or "").endswith("_test")
    assert (replica_engine.url.database or "").endswith("_test")


def test_the_app_under_test_uses_the_test_redis_db() -> None:
    assert redis.connection_pool.connection_kwargs["db"] == get_settings().redis_db
    assert get_settings().redis_db == _test_redis_db(dev_redis_db=-1)
