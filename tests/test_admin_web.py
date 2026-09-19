import pytest
from httpx import AsyncClient

from auth.services.security_service import SecurityService
from core.factories.user_factory import make_email
from core.limiter import limiter
from user.repositories.user_repository import UserRepository

LOGIN_URL = "/admin/login"


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    """/admin/login is capped at 5/minute per IP; the test client's requests
    all share one IP, so multiple tests in this file would trip the limiter."""
    limiter.enabled = False
    yield
    limiter.enabled = True


async def test_admin_users_redirects_when_unauthenticated(client: AsyncClient) -> None:
    response = await client.get("/admin/users")

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


async def test_admin_users_rows_redirects_when_unauthenticated(
    client: AsyncClient,
) -> None:
    response = await client.get("/admin/users/rows")

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


async def test_admin_login_page_renders(client: AsyncClient) -> None:
    response = await client.get(LOGIN_URL)

    assert response.status_code == 200
    assert "Admin Login" in response.text


async def test_admin_login_succeeds_and_reaches_users_page(
    client: AsyncClient, db
) -> None:
    repo = UserRepository(db)
    password = "correct-horse-battery-staple"
    user = await repo.add(
        full_name="Admin",
        email=make_email(),
        password_hash=SecurityService.hash_password(password),
    )
    await repo.update(user.id, is_verified=True, scopes="admin:read")

    response = await client.post(
        LOGIN_URL, data={"email": user.email, "password": password}
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/users"

    users_page = await client.get("/admin/users")
    assert users_page.status_code == 200


async def test_admin_login_rejects_wrong_password(client: AsyncClient, db) -> None:
    repo = UserRepository(db)
    user = await repo.add(
        full_name="Admin",
        email=make_email(),
        password_hash=SecurityService.hash_password("the-real-password"),
    )
    await repo.update(user.id, is_verified=True, scopes="admin:read")

    response = await client.post(
        LOGIN_URL, data={"email": user.email, "password": "wrong-password"}
    )

    assert response.status_code == 401
    assert "Invalid credentials" in response.text


async def test_admin_login_rejects_nonexistent_user(client: AsyncClient) -> None:
    response = await client.post(
        LOGIN_URL, data={"email": make_email(), "password": "whatever"}
    )

    assert response.status_code == 401
    assert "Invalid credentials" in response.text


async def test_admin_login_rejects_unverified_user(client: AsyncClient, db) -> None:
    repo = UserRepository(db)
    password = "correct-horse-battery-staple"
    user = await repo.add(
        full_name="Admin",
        email=make_email(),
        password_hash=SecurityService.hash_password(password),
    )
    await repo.update(user.id, scopes="admin:read")  # is_verified stays False

    response = await client.post(
        LOGIN_URL, data={"email": user.email, "password": password}
    )

    assert response.status_code == 401
    assert "Invalid credentials" in response.text


async def test_admin_login_rejects_verified_user_without_admin_scope(
    client: AsyncClient, db
) -> None:
    repo = UserRepository(db)
    password = "correct-horse-battery-staple"
    user = await repo.add(
        full_name="Regular User",
        email=make_email(),
        password_hash=SecurityService.hash_password(password),
    )
    await repo.update(user.id, is_verified=True)  # default scopes, no admin:read

    response = await client.post(
        LOGIN_URL, data={"email": user.email, "password": password}
    )

    assert response.status_code == 401
    assert "Invalid credentials" in response.text
