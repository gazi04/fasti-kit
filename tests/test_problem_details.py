import pytest
from httpx import AsyncClient

from core.exception import EntityNotFoundError
from main import app


async def _demo_not_found():
    raise EntityNotFoundError("Widget", 42)


async def _demo_broken():
    raise RuntimeError("boom")


app.add_api_route("/__test/problem/domain", _demo_not_found)
app.add_api_route("/__test/problem/unhandled", _demo_broken)

REQUIRED_FIELDS = {"type", "title", "status", "detail", "instance", "correlation_id"}


def _assert_problem(response, status: int) -> dict:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body.keys() >= REQUIRED_FIELDS
    assert body["status"] == status
    return body


async def test_unknown_route_is_problem_json(client: AsyncClient) -> None:
    _assert_problem(await client.get("/api/v1/nope"), 404)


async def test_auth_error_is_problem_json(client: AsyncClient) -> None:
    body = _assert_problem(await client.get("/api/v1/user/get"), 401)
    assert body["type"] == "about:blank"
    assert body["title"] == "Unauthorized"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "secret-pass"},
        {"email": "a@b.com"},  # missing password
    ],
)
async def test_validation_error_sanitized(client: AsyncClient, payload: dict) -> None:
    body = _assert_problem(await client.post("/api/v1/user/create", json=payload), 422)
    assert body["invalid_params"]
    assert all({"name", "reason", "code"} <= e.keys() for e in body["invalid_params"])
    raw = str(body)
    assert "secret-pass" not in raw and "input" not in body  # password not leaked


async def test_domain_exception_is_problem_json(client: AsyncClient) -> None:
    body = _assert_problem(await client.get("/__test/problem/domain"), 404)
    assert body["type"] == "errors/not-found"
    assert body["detail"].startswith("Widget with identifier")


async def test_unhandled_exception_is_generic(client: AsyncClient) -> None:
    body = _assert_problem(await client.get("/__test/problem/unhandled"), 500)
    assert body["detail"] == "Internal server error"
    assert "boom" not in str(body)  # no internal detail leaked


async def test_instance_omits_query_string(client: AsyncClient) -> None:
    body = _assert_problem(await client.get("/api/v1/nope?token=SUPERSECRET"), 404)
    assert body["instance"] == "/api/v1/nope"
    assert "SUPERSECRET" not in str(body)


async def test_correlation_id_matches_request_header(client: AsyncClient) -> None:
    response = await client.get("/api/v1/nope", headers={"X-Request-ID": "abc-123"})
    body = _assert_problem(response, 404)
    assert body["correlation_id"] == "abc-123"
    assert response.headers["x-request-id"] == "abc-123"


async def test_rate_limit_is_problem_json(client: AsyncClient) -> None:
    from core.limiter import limiter

    limiter.enabled = True
    try:
        for _ in range(6):
            await client.post(
                "/api/v1/auth/login",
                json={"email": "a@b.c", "password": "x"},
            )
        response = await client.post(
            "/api/v1/auth/login", json={"email": "a@b.c", "password": "x"}
        )
    finally:
        limiter.enabled = False
    body = _assert_problem(response, 429)
    assert response.headers.get("retry-after")
