import os

import pytest
from sqlalchemy.engine import make_url

DEFAULT_TEST_REDIS_DB = 15


def _test_database_url(url: str) -> str:
    parsed = make_url(url)
    if not parsed.database:
        raise pytest.UsageError(
            "DATABASE_URL names no database to derive the test one from."
        )
    if parsed.database.endswith("_test"):
        return url
    return parsed.set(database=f"{parsed.database}_test").render_as_string(
        hide_password=False
    )


def _test_redis_db(dev_redis_db: int) -> int:
    test_redis_db = int(os.environ.get("TEST_REDIS_DB", DEFAULT_TEST_REDIS_DB))
    if test_redis_db == dev_redis_db:
        raise pytest.UsageError(
            f"TEST_REDIS_DB ({test_redis_db}) is the dev REDIS_DB; pick another number."
        )
    return test_redis_db


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests() -> None:
    from core.setting import get_settings

    dev = get_settings()
    os.environ["DATABASE_URL"] = _test_database_url(dev.database_url)
    os.environ["DATABASE_REPLICA_URL"] = _test_database_url(dev.get_replica_url)
    os.environ["REDIS_DB"] = str(_test_redis_db(dev.redis_db))
    get_settings.cache_clear()
