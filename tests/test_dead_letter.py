from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from saq.job import Job, Status
from sqlalchemy import func, select

from auth.dependencies import auth
from core.dead_letter import hook as dead_letter_hook
from core.dead_letter.entity import DeadLetterJob
from core.dead_letter.hook import record_dead_letter, record_dead_letter_job
from core.dead_letter.model import DeadLetterJobModel
from core.dead_letter.repository import DeadLetterJobRepository
from core.dead_letter.service import DeadLetterJobService

DLQ_URL = "/api/admin/tasks/dlq"


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    from core.limiter import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


class _NullCloseSession:
    """Hand the transactional test session to the hook's
    `async with AsyncSessionLocal() as db` without letting it close the session."""

    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info) -> bool:
        return False


@pytest.fixture
def hook_session(db, monkeypatch):
    """Point `record_dead_letter`'s own session at the transactional `db`."""
    monkeypatch.setattr(
        dead_letter_hook, "AsyncSessionLocal", lambda: _NullCloseSession(db)
    )
    return db


def _failed_job(**overrides) -> Job:
    job = Job(
        function="send_email_task",
        kwargs={"subject": "s", "recipients": ["a@example.com"]},
        key=f"job-{uuid4().hex[:8]}",
    )
    job.status = Status.FAILED
    job.error = "Traceback (most recent call last):\n  RuntimeError: boom"
    job.attempts = 3
    for name, value in overrides.items():
        setattr(job, name, value)
    return job


async def _count(db) -> int:
    return await db.scalar(select(func.count()).select_from(DeadLetterJobModel)) or 0


async def _rows(db) -> list[DeadLetterJobModel]:
    return list((await db.scalars(select(DeadLetterJobModel))).all())


# --------------------------------------------------------------------------- hook


async def test_hook_records_a_failed_job(hook_session) -> None:
    job = _failed_job()

    await record_dead_letter({"job": job})

    rows = await _rows(hook_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.job_key == job.key
    assert row.function == "send_email_task"
    assert row.queue_name == "default"
    assert row.kwargs == {"subject": "s", "recipients": ["a@example.com"]}
    assert row.status == "failed"
    assert row.error is not None and "RuntimeError: boom" in row.error
    assert row.attempts == 3
    assert row.retried_at is None


async def test_hook_records_an_aborted_job(hook_session) -> None:
    await record_dead_letter(
        {"job": _failed_job(status=Status.ABORTED, error="aborted")}
    )

    rows = await _rows(hook_session)
    assert len(rows) == 1
    assert rows[0].status == "aborted"


@pytest.mark.parametrize("status", [Status.COMPLETE, Status.QUEUED, Status.ACTIVE])
async def test_hook_skips_non_terminal_failure(hook_session, status) -> None:
    await record_dead_letter({"job": _failed_job(status=status)})
    assert await _count(hook_session) == 0


async def test_hook_is_a_noop_without_a_job(hook_session) -> None:
    await record_dead_letter({"job": None})
    await record_dead_letter({})
    assert await _count(hook_session) == 0


async def test_hook_coerces_missing_kwargs(hook_session) -> None:
    await record_dead_letter({"job": _failed_job(kwargs=None)})

    rows = await _rows(hook_session)
    assert len(rows) == 1
    assert rows[0].kwargs == {}


async def test_hook_swallows_its_own_failure(hook_session, monkeypatch) -> None:
    async def _boom(self, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(DeadLetterJobRepository, "record", _boom)

    # Must not propagate — a capture failure cannot be allowed to crash the worker.
    await record_dead_letter({"job": _failed_job()})


async def test_record_dead_letter_job_pure(db) -> None:
    entity = await record_dead_letter_job(db, _failed_job())
    assert entity.status == "failed"
    assert await _count(db) == 1


# --------------------------------------------------------------------------- repo


async def _record(
    repo: DeadLetterJobRepository,
    *,
    kwargs: dict | None = None,
    status: str = "failed",
) -> DeadLetterJob:
    return await repo.record(
        job_key=f"k-{uuid4().hex[:8]}",
        function="send_email_task",
        queue_name="default",
        kwargs={"a": 1} if kwargs is None else kwargs,
        status=status,
        error="trace",
        attempts=3,
    )


async def test_repo_list_orders_newest_first_and_filters_unresolved(db) -> None:
    repo = DeadLetterJobRepository(db)
    old = await _record(repo)
    new = await _record(repo)
    old_model = await db.get(DeadLetterJobModel, old.id)
    old_model.failed_at = datetime.now(UTC) - timedelta(hours=1)
    new_model = await db.get(DeadLetterJobModel, new.id)
    new_model.retried_at = datetime.now(UTC)
    await db.commit()

    page = await repo.list()
    assert [item.id for item in page.items] == [new.id, old.id]

    unresolved = await repo.list(unresolved_only=True)
    assert [item.id for item in unresolved.items] == [old.id]


async def test_repo_get_hit_and_miss(db) -> None:
    repo = DeadLetterJobRepository(db)
    row = await _record(repo)
    fetched = await repo.get(row.id)
    assert fetched is not None
    assert fetched.job_key == row.job_key
    assert await repo.get(uuid4()) is None


async def test_repo_mark_retried_sets_timestamp(db) -> None:
    repo = DeadLetterJobRepository(db)
    row = await _record(repo)
    updated = await repo.mark_retried(row.id)
    assert updated is not None
    assert updated.retried_at is not None
    assert await repo.mark_retried(uuid4()) is None


async def test_repo_delete_reports_existence(db) -> None:
    repo = DeadLetterJobRepository(db)
    row = await _record(repo)
    assert await repo.delete(row.id) is True
    assert await repo.delete(row.id) is False


async def test_repo_purge_honours_filters(db) -> None:
    repo = DeadLetterJobRepository(db)
    stale_retried = await _record(repo)
    fresh_retried = await _record(repo)
    stale_unresolved = await _record(repo)

    stale_r = await db.get(DeadLetterJobModel, stale_retried.id)
    stale_r.failed_at = datetime.now(UTC) - timedelta(days=40)
    stale_r.retried_at = datetime.now(UTC)
    fresh_r = await db.get(DeadLetterJobModel, fresh_retried.id)
    fresh_r.retried_at = datetime.now(UTC)
    stale_u = await db.get(DeadLetterJobModel, stale_unresolved.id)
    stale_u.failed_at = datetime.now(UTC) - timedelta(days=40)
    await db.commit()

    deleted = await repo.purge(
        before=datetime.now(UTC) - timedelta(days=30), only_retried=True
    )
    assert deleted == 1
    surviving = {row.id for row in await _rows(db)}
    assert surviving == {fresh_retried.id, stale_unresolved.id}


# ------------------------------------------------------------------------ service


async def test_service_retry_enqueues_and_marks_retried(db, monkeypatch) -> None:
    calls: list[dict] = []

    async def _fake_enqueue(task_name, *, key, **kwargs):
        calls.append({"task_name": task_name, "key": key, **kwargs})
        return None

    monkeypatch.setattr("core.dead_letter.service.enqueue_task", _fake_enqueue)

    repo = DeadLetterJobRepository(db)
    service = DeadLetterJobService(repo)
    row = await _record(repo, kwargs={"recipients": ["x@example.com"]})

    result = await service.retry_job(row.id)

    assert result is not None
    assert result.retried_at is not None
    assert calls == [
        {
            "task_name": "send_email_task",
            "key": f"dlq-retry:{row.id}",
            "kwargs": {"recipients": ["x@example.com"]},
        }
    ]


async def test_service_retry_rejects_a_second_attempt(db, monkeypatch) -> None:
    calls: list = []

    async def _fake_enqueue(task_name, *, key, **kwargs):
        calls.append(key)

    monkeypatch.setattr("core.dead_letter.service.enqueue_task", _fake_enqueue)

    repo = DeadLetterJobRepository(db)
    service = DeadLetterJobService(repo)
    row = await _record(repo)

    await service.retry_job(row.id)
    with pytest.raises(ValueError, match="already retried"):
        await service.retry_job(row.id)

    assert calls == [f"dlq-retry:{row.id}"]  # enqueue not called the second time


async def test_service_retry_unknown_id_returns_none(db) -> None:
    service = DeadLetterJobService(DeadLetterJobRepository(db))
    assert await service.retry_job(uuid4()) is None


# ------------------------------------------------------------------------- router


def _admin_headers(scopes: list[str] | None = None) -> dict[str, str]:
    token = auth.create_access_token(uid=str(uuid4()), scopes=scopes or [])
    return {"Authorization": f"Bearer {token}"}


async def _fake_enqueue(*args, **kwargs):
    return None


async def test_router_requires_admin_read_scope(client) -> None:
    unscoped = await client.get(DLQ_URL, headers=_admin_headers())
    assert unscoped.status_code == 403

    scoped = await client.get(DLQ_URL, headers=_admin_headers(["admin:read"]))
    assert scoped.status_code == 200


async def test_router_lists_and_retries_and_purges(client, db, monkeypatch) -> None:
    monkeypatch.setattr("core.dead_letter.service.enqueue_task", _fake_enqueue)
    headers = _admin_headers(["admin:read"])
    row = await _record(DeadLetterJobRepository(db))

    listing = await client.get(DLQ_URL, headers=headers)
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["items"]] == [str(row.id)]

    retried = await client.post(f"{DLQ_URL}/{row.id}/retry", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["job_key"] == row.job_key

    second = await client.post(f"{DLQ_URL}/{row.id}/retry", headers=headers)
    assert second.status_code == 409

    unbounded = await client.post(
        f"{DLQ_URL}/purge", headers=headers, json={"only_retried": False}
    )
    assert unbounded.status_code == 400

    purged = await client.post(
        f"{DLQ_URL}/purge", headers=headers, json={"only_retried": True}
    )
    assert purged.status_code == 200
    assert purged.json()["deleted"] == 1


async def test_router_get_missing_returns_404(client) -> None:
    response = await client.get(
        f"{DLQ_URL}/{uuid4()}", headers=_admin_headers(["admin:read"])
    )
    assert response.status_code == 404


async def test_router_get_and_delete_single(client, db) -> None:
    headers = _admin_headers(["admin:read"])
    row = await _record(DeadLetterJobRepository(db))

    fetched = await client.get(f"{DLQ_URL}/{row.id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["job_key"] == row.job_key

    deleted = await client.delete(f"{DLQ_URL}/{row.id}", headers=headers)
    assert deleted.status_code == 204

    again = await client.delete(f"{DLQ_URL}/{row.id}", headers=headers)
    assert again.status_code == 404


# ------------------------------------------------------------------- cleanup task


async def test_cleanup_dead_letter_task_runs_without_error() -> None:
    from core.worker.tasks import cleanup_dead_letter_task

    result = await cleanup_dead_letter_task(ctx={})
    assert result["status"] == "completed"
    assert "deleted" in result
