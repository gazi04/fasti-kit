from httpx import AsyncClient


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
