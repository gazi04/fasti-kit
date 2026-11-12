import asyncio
import contextlib
import contextvars
import secrets
import threading
import time

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import func, select

from auth.models import RefreshSessionModel
from auth.services.password_hasher import PasswordHasher
from auth.services.security_service import SecurityService
from core.exception import ServiceUnavailableError
from core.factories.user_factory import make_email
from core.limiter import limiter
from core.password import BCRYPT_MAX_PASSWORD_BYTES
from core.setting import cgroup_cpu_limit
from user.repositories.user_repository import UserRepository

LOGIN_URL = "/api/v1/auth/login"
USERS_URL = "/api/v1/users"


class BlockingJob:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.running = 0
        self.peak = 0
        self._lock = threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        self.release.wait(timeout=5)
        with self._lock:
            self.running -= 1
        return "done"


async def _wait_until(condition) -> None:
    for _ in range(200):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met in time")


def _rejected_total() -> float:
    return REGISTRY.get_sample_value("password_hash_rejected_total") or 0.0


@pytest.fixture
def hasher():
    instance = PasswordHasher(workers=2, queue_per_worker=2, retry_after=7)
    yield instance
    instance.shutdown()


def _fill(hasher: PasswordHasher, job: BlockingJob) -> list[asyncio.Task]:
    return [asyncio.create_task(hasher.run(job)) for _ in range(hasher.max_pending)]


async def test_runs_the_function_and_returns_its_result(hasher) -> None:
    assert await hasher.run(lambda a, b: a + b, 1, b=2) == 3
    assert hasher.pending == 0


async def test_exception_in_the_function_frees_the_slot(hasher) -> None:
    def boom() -> None:
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        await hasher.run(boom)
    assert hasher.pending == 0


async def test_context_variables_reach_the_worker_thread(hasher) -> None:
    correlation = contextvars.ContextVar("correlation", default="unset")
    correlation.set("req-42")

    assert await hasher.run(correlation.get) == "req-42"


async def test_never_runs_more_hashes_than_workers(hasher) -> None:
    job = BlockingJob()
    tasks = _fill(hasher, job)

    await _wait_until(lambda: job.running == hasher.workers)
    await asyncio.sleep(0.05)
    assert job.running == hasher.workers

    job.release.set()
    assert await asyncio.gather(*tasks) == ["done"] * hasher.max_pending
    assert job.peak == hasher.workers
    assert hasher.pending == 0


async def test_refuses_work_beyond_the_pending_limit(hasher) -> None:
    job = BlockingJob()
    tasks = _fill(hasher, job)
    await _wait_until(lambda: hasher.pending == hasher.max_pending)
    rejected_before = _rejected_total()

    with pytest.raises(ServiceUnavailableError) as error:
        await hasher.run(job)

    assert error.value.status_code == 503
    assert error.value.headers is not None
    retry_after = int(error.value.headers["Retry-After"])
    assert hasher.retry_after <= retry_after <= 2 * hasher.retry_after
    assert _rejected_total() == rejected_before + 1
    assert hasher.pending == hasher.max_pending

    job.release.set()
    await asyncio.gather(*tasks)
    assert await hasher.run(job) == "done"


async def test_cancelled_waiter_gives_its_slot_back_at_once(hasher) -> None:
    job = BlockingJob()
    tasks = _fill(hasher, job)
    await _wait_until(lambda: job.running == hasher.workers)

    tasks[-1].cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tasks[-1]

    assert hasher.pending == hasher.max_pending - 1
    job.release.set()
    await asyncio.gather(*tasks[:-1])
    assert hasher.pending == 0


async def test_cancelled_running_hash_keeps_its_slot_until_it_ends(hasher) -> None:
    job = BlockingJob()
    tasks = _fill(hasher, job)
    await _wait_until(lambda: job.running == hasher.workers)

    tasks[0].cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tasks[0]

    assert hasher.pending == hasher.max_pending
    with pytest.raises(ServiceUnavailableError):
        await hasher.run(job)

    job.release.set()
    await asyncio.gather(*tasks[1:])
    await _wait_until(lambda: hasher.pending == 0)


async def test_event_loop_stays_responsive_while_saturated(hasher) -> None:
    job = BlockingJob()
    tasks = _fill(hasher, job)
    await _wait_until(lambda: job.running == hasher.workers)

    started = time.perf_counter()
    for _ in range(10):
        await asyncio.sleep(0.005)
    elapsed = time.perf_counter() - started

    job.release.set()
    await asyncio.gather(*tasks)
    assert elapsed < 0.5


async def test_shutdown_cancels_queued_work_and_frees_slots(hasher) -> None:
    job = BlockingJob()
    tasks = _fill(hasher, job)
    await _wait_until(lambda: job.running == hasher.workers)

    hasher.shutdown()
    job.release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert results.count("done") == hasher.workers
    assert all(
        isinstance(result, asyncio.CancelledError)
        for result in results
        if result != "done"
    )
    assert hasher.pending == 0
    assert await hasher.run(lambda: "again") == "again"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("max 100000\n", None),
        ("200000 100000\n", 2),
        ("150000 100000\n", 2),
        ("50000 100000\n", 1),
        ("garbage\n", None),
    ],
)
def test_cgroup_cpu_limit(tmp_path, content, expected) -> None:
    cpu_max = tmp_path / "cpu.max"
    cpu_max.write_text(content)

    assert cgroup_cpu_limit(cpu_max) == expected


def test_cgroup_cpu_limit_without_the_file(tmp_path) -> None:
    assert cgroup_cpu_limit(tmp_path / "missing") is None


async def test_overlong_password_never_matches_and_skips_bcrypt(
    monkeypatch,
) -> None:
    hashed = await SecurityService.hash_password("short")

    async def must_not_run(*args, **kwargs):
        raise AssertionError("bcrypt must not run for an overlong password")

    monkeypatch.setattr(
        "auth.services.security_service.password_hasher.run", must_not_run
    )

    overlong = "a" * (BCRYPT_MAX_PASSWORD_BYTES + 1)
    assert await SecurityService.check_password(overlong, hashed) is False


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture
def full_hasher(monkeypatch):
    instance = PasswordHasher(workers=1, queue_per_worker=1, retry_after=2)
    instance._pending = instance.max_pending
    monkeypatch.setattr("auth.services.security_service.password_hasher", instance)
    return instance


@pytest.mark.parametrize("known_email", [True, False])
async def test_login_is_shed_with_503_whatever_the_account(
    client, db, full_hasher, known_email
) -> None:
    email = make_email()
    user = None
    if known_email:
        user = await UserRepository(db).add("Busy", email, secrets.token_hex(8))
        await UserRepository(db).update(user.id, is_verified=True, is_active=True)

    response = await client.post(
        LOGIN_URL, json={"email": email, "password": secrets.token_hex(8)}
    )

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert 2 <= int(response.headers["retry-after"]) <= 4
    assert response.json()["type"] == "errors/service-unavailable"
    if user is not None:
        sessions = await db.scalar(
            select(func.count())
            .select_from(RefreshSessionModel)
            .where(RefreshSessionModel.user_id == user.id)
        )
        assert sessions == 0


async def test_login_with_overlong_password_is_401_not_500(client) -> None:
    response = await client.post(
        LOGIN_URL,
        json={"email": make_email(), "password": "a" * 100},
    )

    assert response.status_code == 401


async def test_signup_rejects_a_password_bcrypt_cannot_hash(client) -> None:
    response = await client.post(
        USERS_URL,
        json={"name": "Long", "email": make_email(), "password": "é" * 37},
    )

    assert response.status_code == 422
