import ipaddress
import secrets
from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from core.limiter import limiter


@pytest.fixture(autouse=True)
def _enable_limiter() -> Iterator[None]:
    previous = limiter.enabled
    limiter.enabled = True
    yield
    limiter.enabled = previous


def _unused_ip() -> str:
    network = ipaddress.IPv6Network("2001:db8::/32")
    return str(network[secrets.randbits(96)])


def _email() -> str:
    return f"{secrets.token_hex(6)}@example.com"


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("POST", "/api/v1/users", "register"),
        ("GET", "/api/v1/auth/verify-email?token=invalid", None),
        ("POST", "/api/v1/auth/resend-verification", "email"),
        ("POST", "/api/v1/auth/forgot-password", "email"),
        ("POST", "/api/v1/auth/reset-password", "reset"),
    ],
)
async def test_limited_route_sends_rate_limit_headers(
    client: AsyncClient, method: str, url: str, body: str | None
) -> None:
    payloads = {
        None: None,
        "register": {
            "name": "Rate Limit",
            "email": _email(),
            "password": secrets.token_urlsafe(12),
        },
        "email": {"email": _email()},
        "reset": {"token": "invalid", "new_password": secrets.token_urlsafe(12)},
    }

    response = await client.request(
        method,
        url,
        json=payloads[body],
        headers={"X-Forwarded-For": _unused_ip()},
    )

    assert response.status_code != 500
    if response.is_success:
        assert "x-ratelimit-limit" in response.headers
