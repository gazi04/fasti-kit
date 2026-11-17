import pytest

from core import deferred_tasks
from core.database import after_commit, transaction
from core.deferred_tasks import EnqueueAfterCommit
from core.factories.user_factory import make_email
from core.limiter import limiter
from user.repositories.user_repository import UserRepository

PAYLOAD = {"subject": "s", "recipients": ["a@example.com"], "body": "b"}


@pytest.fixture(autouse=True)
def _enqueue_after_commit(monkeypatch):
    monkeypatch.setattr(deferred_tasks, "_factory", EnqueueAfterCommit)


@pytest.fixture
def _no_rate_limit():
    limiter.enabled = False
    yield
    limiter.enabled = True


async def test_callbacks_run_only_after_the_commit(db) -> None:
    order: list[str] = []
    commit = db.commit

    async def recording_commit() -> None:
        order.append("commit")
        await commit()

    async def callback() -> None:
        order.append("callback")

    db.commit = recording_commit
    async with transaction(db):
        after_commit(db, callback)
        assert order == []

    assert order == ["commit", "callback"]


async def test_callbacks_are_dropped_when_the_transaction_fails(db) -> None:
    ran: list[str] = []

    async def callback() -> None:
        ran.append("callback")

    with pytest.raises(RuntimeError):
        async with transaction(db):
            after_commit(db, callback)
            raise RuntimeError("write failed")

    async with transaction(db):
        pass

    assert ran == []


async def test_a_failing_callback_is_logged_not_raised(db, caplog) -> None:
    async def broken() -> None:
        raise RuntimeError("redis down")

    async with transaction(db):
        after_commit(db, broken)

    assert "After-commit callback failed" in caplog.text


async def test_stage_add_enqueues_once_after_the_commit(db, enqueued) -> None:
    async with transaction(db):
        await EnqueueAfterCommit(db).stage_add("send_email_task", PAYLOAD)
        assert enqueued == []

    (call,) = enqueued
    assert call["task_name"] == "send_email_task"
    assert call["key"].startswith("send_email_task:")
    assert call["subject"] == "s"


async def test_signup_enqueues_the_verification_email(
    client, db, enqueued, _no_rate_limit
) -> None:
    response = await client.post(
        "/api/v1/users",
        json={"name": "Deferred", "email": make_email(), "password": "pw123456"},
    )

    assert response.status_code == 200, response.text
    assert [call["subject"] for call in enqueued] == ["Verify your email"]


async def test_signup_succeeds_when_the_enqueue_fails(
    client, db, monkeypatch, _no_rate_limit
) -> None:
    async def redis_down(task_name, *, key, **kwargs) -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr(deferred_tasks, "enqueue_task", redis_down)

    response = await client.post(
        "/api/v1/users",
        json={"name": "Saved Anyway", "email": make_email(), "password": "pw123456"},
    )

    assert response.status_code == 200, response.text


async def test_resend_and_forgot_enqueue_one_email_each(
    client, db, enqueued, _no_rate_limit
) -> None:
    user = await UserRepository(db).add("Resend", make_email(), "pw")

    await client.post("/api/v1/auth/resend-verification", json={"email": user.email})
    await client.post("/api/v1/auth/forgot-password", json={"email": user.email})

    subjects = sorted(call["subject"] for call in enqueued)
    assert subjects == ["Reset your password", "Verify your email"]
    refreshed = await UserRepository(db).get(user.id)
    assert refreshed is not None
    assert refreshed.pending_verification_jti is not None
    assert refreshed.pending_password_reset_jti is not None
