import time
from collections.abc import Iterator, Mapping

from prometheus_client import REGISTRY, CollectorRegistry, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import Engine, event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

from core.database import primary_engine, replica_engine
from core.setting import get_settings

HOLD_START_KEY = "metrics_hold_start"

_installed_registries: set[int] = set()


class PoolCollector(Collector):
    def __init__(self, engines: Mapping[str, AsyncEngine], capacity: int) -> None:
        self._engines = engines
        self._capacity = capacity

    def collect(self) -> Iterator[GaugeMetricFamily]:
        connections = GaugeMetricFamily(
            "db_pool_connections",
            "Connections in the SQLAlchemy pool, by state.",
            labels=["engine", "state"],
        )
        capacity = GaugeMetricFamily(
            "db_pool_capacity",
            "Most connections the pool may open (pool size plus max overflow).",
            labels=["engine"],
        )
        for name, engine in self._engines.items():
            pool = engine.pool
            if not isinstance(pool, QueuePool):
                continue
            connections.add_metric([name, "checked_out"], pool.checkedout())
            connections.add_metric([name, "idle"], pool.checkedin())
            capacity.add_metric([name], self._capacity)
        yield connections
        yield capacity


def track_hold_time(sync_engine: Engine, name: str, histogram: Histogram) -> None:
    @event.listens_for(sync_engine, "checkout")
    def _start(dbapi_connection, connection_record, connection_proxy) -> None:
        connection_record.info[HOLD_START_KEY] = time.perf_counter()

    @event.listens_for(sync_engine, "checkin")
    def _stop(dbapi_connection, connection_record) -> None:
        started = connection_record.info.pop(HOLD_START_KEY, None)
        if started is not None:
            histogram.labels(engine=name).observe(time.perf_counter() - started)


def install_pool_metrics(registry: CollectorRegistry = REGISTRY) -> None:
    if id(registry) in _installed_registries:
        return
    _installed_registries.add(id(registry))

    settings = get_settings()
    engines = {"primary": primary_engine, "replica": replica_engine}
    registry.register(
        PoolCollector(engines, settings.db_pool_size + settings.db_max_overflow)
    )
    hold_seconds = Histogram(
        "db_connection_hold_seconds",
        "How long a request keeps a pooled connection checked out.",
        labelnames=["engine"],
        buckets=(
            0.001,
            0.0025,
            0.005,
            0.01,
            0.025,
            0.05,
            0.1,
            0.25,
            0.5,
            1,
            2.5,
            5,
            10,
            30,
        ),
        registry=registry,
    )
    for name, engine in engines.items():
        track_hold_time(engine.sync_engine, name, hold_seconds)
