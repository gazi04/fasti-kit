import pytest
from prometheus_client import CollectorRegistry, Histogram
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from core.metrics import PoolCollector, install_pool_metrics, track_hold_time
from core.setting import get_settings

settings = get_settings()


@pytest.fixture
async def engine():
    engine = create_async_engine(settings.database_url, pool_size=2, max_overflow=1)
    yield engine
    await engine.dispose()


def _pool_value(registry: CollectorRegistry, state: str) -> float | None:
    return registry.get_sample_value(
        "db_pool_connections", {"engine": "primary", "state": state}
    )


async def test_pool_gauges_follow_checkout_and_checkin(engine) -> None:
    registry = CollectorRegistry()
    registry.register(PoolCollector({"primary": engine}, capacity=3))

    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
        assert _pool_value(registry, "checked_out") == 1
        assert _pool_value(registry, "idle") == 0

    assert _pool_value(registry, "checked_out") == 0
    assert _pool_value(registry, "idle") == 1
    assert registry.get_sample_value("db_pool_capacity", {"engine": "primary"}) == 3


async def test_hold_time_is_observed_on_checkin(engine) -> None:
    registry = CollectorRegistry()
    histogram = Histogram(
        "hold_seconds", "test", labelnames=["engine"], registry=registry
    )
    track_hold_time(engine.sync_engine, "primary", histogram)

    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
        assert (
            registry.get_sample_value("hold_seconds_count", {"engine": "primary"})
            is None
        )

    assert registry.get_sample_value("hold_seconds_count", {"engine": "primary"}) == 1


def test_install_twice_on_one_registry_is_a_no_op() -> None:
    registry = CollectorRegistry()

    install_pool_metrics(registry)
    install_pool_metrics(registry)

    assert (
        registry.get_sample_value("db_pool_capacity", {"engine": "replica"})
        == settings.db_pool_size + settings.db_max_overflow
    )
