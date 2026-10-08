import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from core import health
from core.outbox.model import OutboxEvent
from core.outbox.relay import RELAY_HEARTBEAT_KEY, oldest_pending_age, relay_loop
from core.queue import redis, task_queue


@pytest.fixture
async def clean_heartbeat():
    await redis.delete(RELAY_HEARTBEAT_KEY)
    yield
    await redis.delete(RELAY_HEARTBEAT_KEY)


async def _add_event(db, *, age_seconds: float, **fields) -> None:
    db.add(
        OutboxEvent(
            task_name="send_email_task",
            payload={},
            created_at=datetime.now(UTC) - timedelta(seconds=age_seconds),
            **fields,
        )
    )
    await db.flush()


async def test_worker_check_fails_without_workers(monkeypatch) -> None:
    async def no_workers(*args, **kwargs):
        return {"workers": {}}

    monkeypatch.setattr(task_queue, "info", no_workers)

    with pytest.raises(RuntimeError, match="no active SAQ worker"):
        await health._check_worker()


async def test_worker_check_passes_with_a_worker(monkeypatch) -> None:
    async def one_worker(*args, **kwargs):
        return {"workers": {"abc": {}}}

    monkeypatch.setattr(task_queue, "info", one_worker)

    await health._check_worker()


async def test_relay_heartbeat_missing_fails(clean_heartbeat) -> None:
    with pytest.raises(RuntimeError, match="heartbeat missing"):
        await health._check_relay_heartbeat()


async def test_relay_heartbeat_present_passes(clean_heartbeat) -> None:
    await redis.set(RELAY_HEARTBEAT_KEY, "1", ex=30)

    await health._check_relay_heartbeat()


async def test_relay_loop_writes_heartbeat(db, monkeypatch, clean_heartbeat) -> None:
    monkeypatch.setattr("core.outbox.relay.AsyncSessionLocal", lambda: _Ctx(db))
    monkeypatch.setattr("core.outbox.relay.settings.outbox_poll_interval", 0.01)

    task = asyncio.create_task(relay_loop())
    try:
        for _ in range(100):
            if await redis.exists(RELAY_HEARTBEAT_KEY):
                break
            await asyncio.sleep(0.05)
    finally:
        task.cancel()

    assert await redis.exists(RELAY_HEARTBEAT_KEY)
    ttl = await redis.ttl(RELAY_HEARTBEAT_KEY)
    assert 0 < ttl <= 30


class _Ctx:
    def __init__(self, db) -> None:
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc) -> None:
        return None


async def test_oldest_pending_age_is_none_when_empty(db) -> None:
    assert await oldest_pending_age(db) is None


async def test_oldest_pending_age_reports_oldest_pending_row(db) -> None:
    await _add_event(db, age_seconds=10)
    await _add_event(db, age_seconds=300)

    age = await oldest_pending_age(db)

    assert age is not None
    assert 299 <= age < 310


async def test_oldest_pending_age_ignores_dispatched_and_failed(db) -> None:
    now = datetime.now(UTC)
    await _add_event(db, age_seconds=500, dispatched_at=now)
    await _add_event(db, age_seconds=500, failed_at=now)

    assert await oldest_pending_age(db) is None


async def test_backlog_check_fails_when_lag_exceeds_limit(monkeypatch) -> None:
    async def stale(db):
        return 120.0

    monkeypatch.setattr(health, "oldest_pending_age", stale)

    with pytest.raises(RuntimeError, match="120s old"):
        await health._check_outbox_backlog()


async def test_backlog_check_passes_when_empty_or_fresh(monkeypatch) -> None:
    for age in (None, 5.0):

        async def fake(db, age=age):
            return age

        monkeypatch.setattr(health, "oldest_pending_age", fake)
        await health._check_outbox_backlog()


def _stub_checks(monkeypatch, *, fail: str | None) -> None:
    async def ok() -> None:
        return None

    async def bad() -> None:
        raise RuntimeError("boom")

    for name in ("_check_worker", "_check_relay_heartbeat", "_check_outbox_backlog"):
        monkeypatch.setattr(health, name, bad if name == fail else ok)


async def test_workers_endpoint_ok(client: AsyncClient, monkeypatch) -> None:
    _stub_checks(monkeypatch, fail=None)

    response = await client.get("/health/workers")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"worker": "ok", "outbox_relay": "ok", "outbox_backlog": "ok"},
    }


async def test_workers_endpoint_503_names_failing_check(
    client: AsyncClient, monkeypatch
) -> None:
    _stub_checks(monkeypatch, fail="_check_relay_heartbeat")

    response = await client.get("/health/workers")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["outbox_relay"] == "unhealthy: boom"
    assert body["checks"]["worker"] == "ok"


async def test_ready_does_not_probe_workers(client: AsyncClient, monkeypatch) -> None:
    _stub_checks(monkeypatch, fail="_check_worker")

    response = await client.get("/health/ready")

    assert "worker" not in response.json()["checks"]
