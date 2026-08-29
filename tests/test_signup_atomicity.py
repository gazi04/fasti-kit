"""
Regression tests for the two-transaction signup bug.

POST /user/create used to commit the user row, then commit the verification
jti separately. A failure on the second write left the account existing,
unverified, with a NULL jti — and the caller's retry hit 409 with no route
back except /resend-verification. Both writes now share one transaction.
"""

import pytest
from sqlalchemy import select

from core.factories.user_factory import make_email
from user.models import UserModel
from user.repositories.user_repository import UserRepository

CREATE_URL = "/api/v1/user/create"


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    """/user/create is capped at 5/minute against a shared Redis store, so
    several signups in one suite run would 429. The cap itself is covered by
    tests/test_problem_details.py."""
    from core.limiter import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


async def _row_for(db, email: str) -> UserModel | None:
    return await db.scalar(select(UserModel).where(UserModel.email == email))


async def test_create_user_persists_user_and_jti(client, db) -> None:
    """The happy path commits both writes."""
    email = make_email()

    response = await client.post(
        CREATE_URL,
        json={"name": "Atomic Signup", "email": email, "password": "pw123456"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["email"] == email

    row = await _row_for(db, email)
    assert row is not None
    assert row.pending_verification_jti is not None, (
        "the jti must be committed with the user, not in a second transaction"
    )


async def test_create_user_leaves_no_row_when_second_write_fails(
    client, db, monkeypatch
) -> None:
    """The whole signup rolls back — no half-created account."""
    email = make_email()

    async def failing_update(self, id, auto_commit=True, **fields):
        raise RuntimeError("simulated failure stamping the verification jti")

    monkeypatch.setattr(UserRepository, "update", failing_update)

    response = await client.post(
        CREATE_URL,
        json={"name": "Doomed Signup", "email": email, "password": "pw123456"},
    )

    assert response.status_code == 500

    row = await _row_for(db, email)
    assert row is None, (
        "the user row must not survive a failed signup — it used to, "
        "leaving the account unrecoverable behind a 409 on retry"
    )


async def test_create_user_can_be_retried_after_a_failure(
    client, db, monkeypatch
) -> None:
    """Because nothing persisted, the same email is still free."""
    email = make_email()

    async def failing_update(self, id, auto_commit=True, **fields):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(UserRepository, "update", failing_update)
    first = await client.post(
        CREATE_URL, json={"name": "Retry Me", "email": email, "password": "pw123456"}
    )
    assert first.status_code == 500

    monkeypatch.undo()
    second = await client.post(
        CREATE_URL, json={"name": "Retry Me", "email": email, "password": "pw123456"}
    )

    assert second.status_code == 200, (
        f"retry should succeed, got {second.status_code}: {second.text}"
    )
    row = await _row_for(db, email)
    assert row is not None and row.pending_verification_jti is not None


async def test_duplicate_email_still_returns_409(client, db) -> None:
    """The savepoint flush must keep translating IntegrityError -> 409."""
    email = make_email()
    await UserRepository(db).add("First", email, "pw")

    response = await client.post(
        CREATE_URL, json={"name": "Second", "email": email, "password": "pw123456"}
    )

    assert response.status_code == 409


async def test_duplicate_email_leaves_the_session_usable(db) -> None:
    """_flush_or_raise uses a SAVEPOINT, so a rejected insert must not poison
    the caller's transaction the way the old rollback-on-IntegrityError did."""
    repo = UserRepository(db)
    email = make_email()
    await repo.add("First", email, "pw")

    with pytest.raises(ValueError, match="Email taken"):
        await repo.add("Second", email, "pw")

    # The outer transaction is still alive and the first row is intact.
    survivor = await _row_for(db, email)
    assert survivor is not None
    assert survivor.full_name == "First"

    other = await repo.add("Unaffected", make_email(), "pw")
    assert other.id is not None
