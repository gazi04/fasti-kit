from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from core.factories.user_factory import make_email
from core.outbox import relay
from core.outbox.model import OutboxEvent
from core.outbox.relay import cleanup_dispatched, dispatch_pending
from core.outbox.repository import OutboxRepository
from core.setting import get_settings
from user.models import UserModel
from user.repositories.user_repository import UserRepository

CREATE_URL = "/api/v1/user/create"
PAYLOAD = {"subject": "s", "recipients": ["a@example.com"], "body": "b"}


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    from core.limiter import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


@pytest.fixture
def recorded_enqueue(monkeypatch):
    calls: list[dict] = []

    async def _fake_enqueue(task_name, *, key, **kwargs):
        calls.append({"task_name": task_name, "key": key, **kwargs})
        return None

    monkeypatch.setattr(relay, "enqueue_task", _fake_enqueue)
    return calls


async def _count_outbox(db) -> int:
    return await db.scalar(select(func.count()).select_from(OutboxEvent)) or 0


async def test_add_commits_atomically_with_a_business_write(db) -> None:
    user_repo = UserRepository(db)
    outbox_repo = OutboxRepository(db)

    user = await user_repo.add("Outbox Atomic", make_email(), "pw", auto_commit=False)
    await outbox_repo.add("send_email_task", PAYLOAD)
    await db.commit()

    assert await _count_outbox(db) == 1
    assert await user_repo.get(user.id) is not None


async def test_add_rolls_back_with_the_business_write(db) -> None:
    outbox_repo = OutboxRepository(db)
    email = make_email()

    await UserRepository(db).add("Doomed", email, "pw", auto_commit=False)
    await outbox_repo.add("send_email_task", PAYLOAD)
    await db.rollback()

    assert await _count_outbox(db) == 0
    row = await db.scalar(select(UserModel).where(UserModel.email == email))
    assert row is None


async def test_dispatch_pending_enqueues_with_dedup_key_and_marks_dispatched(
    db, recorded_enqueue
) -> None:
    outbox_repo = OutboxRepository(db)
    a = await outbox_repo.add("send_email_task", PAYLOAD)
    b = await outbox_repo.add("send_email_task", {**PAYLOAD, "subject": "s2"})
    await db.commit()

    dispatched, failed = await dispatch_pending(db, batch_size=10)

    assert (dispatched, failed) == (2, 0)
    assert {c["key"] for c in recorded_enqueue} == {f"outbox:{a.id}", f"outbox:{b.id}"}
    assert recorded_enqueue[0]["subject"] == "s"
    assert recorded_enqueue[0]["recipients"] == ["a@example.com"]

    for row in (await db.scalars(select(OutboxEvent))).all():
        assert row.dispatched_at is not None


async def test_dispatch_pending_records_failure_without_marking_dispatched(
    db, monkeypatch
) -> None:
    async def _boom(task_name, *, key, **kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(relay, "enqueue_task", _boom)

    row = await OutboxRepository(db).add("send_email_task", PAYLOAD)
    await db.commit()

    dispatched, failed = await dispatch_pending(db, batch_size=10)

    assert (dispatched, failed) == (0, 1)
    refreshed = await db.get(OutboxEvent, row.id)
    assert refreshed.dispatched_at is None
    assert refreshed.failed_at is None
    assert refreshed.attempts == 1
    assert "redis down" in refreshed.last_error


async def test_dispatch_pending_parks_row_after_max_attempts(db, monkeypatch) -> None:
    async def _boom(task_name, *, key, **kwargs):
        raise RuntimeError("still down")

    monkeypatch.setattr(relay, "enqueue_task", _boom)

    row = await OutboxRepository(db).add("send_email_task", PAYLOAD)
    row.attempts = get_settings().outbox_max_attempts - 1
    await db.commit()

    _, failed = await dispatch_pending(db, batch_size=10)

    assert failed == 1
    refreshed = await db.get(OutboxEvent, row.id)
    assert refreshed.failed_at is not None

    _, failed_again = await dispatch_pending(db, batch_size=10)
    assert failed_again == 0


async def test_dispatch_pending_skips_dispatched_and_failed_rows(
    db, recorded_enqueue
) -> None:
    outbox_repo = OutboxRepository(db)
    done = await outbox_repo.add("send_email_task", PAYLOAD)
    done.dispatched_at = datetime.now(UTC)
    dead = await outbox_repo.add("send_email_task", PAYLOAD)
    dead.failed_at = datetime.now(UTC)
    pending = await outbox_repo.add("send_email_task", PAYLOAD)
    await db.commit()

    dispatched, failed = await dispatch_pending(db, batch_size=10)

    assert (dispatched, failed) == (1, 0)
    assert [c["key"] for c in recorded_enqueue] == [f"outbox:{pending.id}"]


async def test_cleanup_dispatched_deletes_only_old_dispatched_rows(db) -> None:
    outbox_repo = OutboxRepository(db)
    retention = get_settings().outbox_retention_days

    old = await outbox_repo.add("send_email_task", PAYLOAD)
    old.dispatched_at = datetime.now(UTC) - timedelta(days=retention + 1)
    recent = await outbox_repo.add("send_email_task", PAYLOAD)
    recent.dispatched_at = datetime.now(UTC)
    pending = await outbox_repo.add("send_email_task", PAYLOAD)
    await db.commit()

    deleted = await cleanup_dispatched(db)

    assert deleted == 1
    surviving = {r.id for r in (await db.scalars(select(OutboxEvent))).all()}
    assert surviving == {recent.id, pending.id}


async def test_create_user_writes_a_single_outbox_row(client, db) -> None:
    email = make_email()

    response = await client.post(
        CREATE_URL,
        json={"name": "Outbox Signup", "email": email, "password": "pw123456"},
    )
    assert response.status_code == 200, response.text

    rows = (await db.scalars(select(OutboxEvent))).all()
    assert len(rows) == 1
    assert rows[0].task_name == "send_email_task"
    assert rows[0].payload["subject"] == "Verify your email"
    assert rows[0].payload["recipients"] == [email]
    assert rows[0].dispatched_at is None


async def test_failed_signup_leaves_no_outbox_row(client, db, monkeypatch) -> None:
    async def failing_update(self, id, auto_commit=True, **fields):
        raise RuntimeError("simulated jti failure")

    monkeypatch.setattr(UserRepository, "update", failing_update)

    response = await client.post(
        CREATE_URL,
        json={"name": "Doomed", "email": make_email(), "password": "pw123456"},
    )
    assert response.status_code == 500
    assert await _count_outbox(db) == 0


async def test_resend_verification_writes_outbox_row_for_unverified_user(
    client, db
) -> None:
    email = make_email()
    await UserRepository(db).add("Unverified", email, "pw")

    response = await client.post(
        "/api/v1/auth/resend-verification", json={"email": email}
    )
    assert response.status_code == 200

    rows = (await db.scalars(select(OutboxEvent))).all()
    assert len(rows) == 1
    assert rows[0].payload["subject"] == "Verify your email"


async def test_forgot_password_writes_outbox_row_for_active_user(client, db) -> None:
    email = make_email()
    user = await UserRepository(db).add("Active", email, "pw")
    await UserRepository(db).update(user.id, is_verified=True)

    response = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert response.status_code == 200

    rows = (await db.scalars(select(OutboxEvent))).all()
    assert len(rows) == 1
    assert rows[0].payload["subject"] == "Reset your password"
