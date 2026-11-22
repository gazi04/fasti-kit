import pytest
from httpx import AsyncClient

from core import health
from core.outbox.health import outbox_checks
from core.queue import task_queue
from main import app


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


async def _no_outbox_checks() -> dict:
    return {}


@pytest.fixture
def worker_only():
    app.dependency_overrides[outbox_checks] = _no_outbox_checks
    yield
    app.dependency_overrides.pop(outbox_checks, None)


def _stub_worker(monkeypatch, *, healthy: bool) -> None:
    async def ok() -> None:
        return None

    async def bad() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(health, "_check_worker", ok if healthy else bad)


async def test_workers_endpoint_ok(
    client: AsyncClient, monkeypatch, worker_only
) -> None:
    _stub_worker(monkeypatch, healthy=True)

    response = await client.get("/health/workers")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"worker": "ok"}}


async def test_workers_endpoint_503_names_failing_check(
    client: AsyncClient, monkeypatch, worker_only
) -> None:
    _stub_worker(monkeypatch, healthy=False)

    response = await client.get("/health/workers")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unhealthy",
        "checks": {"worker": "unhealthy: boom"},
    }


async def test_ready_does_not_probe_workers(client: AsyncClient, monkeypatch) -> None:
    _stub_worker(monkeypatch, healthy=False)

    response = await client.get("/health/ready")

    assert "worker" not in response.json()["checks"]
