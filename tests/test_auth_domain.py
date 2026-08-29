"""
Integration tests for the /auth/login timing-oracle fix: bcrypt must run
exactly once per attempt regardless of whether the account exists, is
active, or is verified — otherwise response timing leaks account state.

Timing itself isn't asserted here (flaky by nature in CI); these assert the
functional invariant the fix guarantees instead — every failure path
returns the identical generic 401, so a client (and, if it mattered, a
timing side-channel) can't distinguish "no such user" from "wrong password"
from "inactive"/"unverified". Manual timing comparison:
    curl -w "%{time_total}\\n" -o /dev/null -s -X POST \\
        http://localhost:8000/api/v1/auth/login \\
        -H "Content-Type: application/json" \\
        -d '{"email": "nobody@nowhere.invalid", "password": "x"}'
"""

import pytest

from auth.services.security_service import SecurityService
from core.factories.user_factory import make_email
from core.limiter import limiter
from user.repositories.user_repository import UserRepository

LOGIN_URL = "/api/v1/auth/login"


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    """/login is capped at 5/minute per IP; the test client's requests all
    share one IP, so multiple tests in this file would trip the limiter."""
    limiter.enabled = False
    yield
    limiter.enabled = True


async def test_login_rejects_nonexistent_user(client) -> None:
    response = await client.post(
        LOGIN_URL, json={"email": make_email(), "password": "whatever"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


async def test_login_rejects_wrong_password(client, db) -> None:
    repo = UserRepository(db)
    email = make_email()
    user = await repo.add(
        "Login Wrong Pw", email, SecurityService.hash_password("correct")
    )
    await repo.update(user.id, is_verified=True)

    response = await client.post(LOGIN_URL, json={"email": email, "password": "wrong"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


async def test_login_rejects_unverified_user_with_correct_password(client, db) -> None:
    repo = UserRepository(db)
    email = make_email()
    await repo.add("Login Unverified", email, SecurityService.hash_password("correct"))

    response = await client.post(
        LOGIN_URL, json={"email": email, "password": "correct"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


async def test_login_rejects_inactive_user_with_correct_password(client, db) -> None:
    repo = UserRepository(db)
    email = make_email()
    user = await repo.add(
        "Login Inactive", email, SecurityService.hash_password("correct")
    )
    await repo.update(user.id, is_verified=True)
    await repo.delete(user.id)  # soft-delete -> is_active False

    response = await client.post(
        LOGIN_URL, json={"email": email, "password": "correct"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


async def test_login_succeeds_for_active_verified_user(client, db) -> None:
    repo = UserRepository(db)
    email = make_email()
    user = await repo.add(
        "Login Happy Path", email, SecurityService.hash_password("correct")
    )
    await repo.update(user.id, is_verified=True)

    response = await client.post(
        LOGIN_URL, json={"email": email, "password": "correct"}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
