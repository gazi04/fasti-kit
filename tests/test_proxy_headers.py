import ipaddress
import secrets
from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from core.limiter import limiter
from core.setting import Settings
from main import app

LOGIN_URL = "/api/v1/auth/login"
LOGIN_LIMIT = 5


@pytest.fixture(autouse=True)
def _enable_limiter() -> Iterator[None]:
    previous = limiter.enabled
    limiter.enabled = True
    yield
    limiter.enabled = previous


def _unused_ip() -> str:
    network = ipaddress.IPv6Network("2001:db8::/32")
    return str(network[secrets.randbits(96)])


async def _login(client: AsyncClient, forwarded_for: str) -> int:
    response = await client.post(
        LOGIN_URL,
        json={"email": "nobody@example.com", "password": "wrong"},
        headers={"X-Forwarded-For": forwarded_for},
    )
    return response.status_code


async def test_trusted_proxy_limits_each_forwarded_client_separately(
    client: AsyncClient,
) -> None:
    first_client, second_client = _unused_ip(), _unused_ip()

    statuses = [await _login(client, first_client) for _ in range(LOGIN_LIMIT)]
    assert 429 not in statuses
    assert await _login(client, first_client) == 429

    assert await _login(client, second_client) == 401


async def test_untrusted_peer_cannot_spoof_forwarded_for(client: AsyncClient) -> None:
    peer = (_unused_ip(), 4321)
    async with AsyncClient(
        transport=ASGITransport(app=app, client=peer), base_url="http://test"
    ) as direct:
        statuses = [await _login(direct, _unused_ip()) for _ in range(LOGIN_LIMIT)]
        assert 429 not in statuses
        assert await _login(direct, _unused_ip()) == 429


@pytest.mark.parametrize(
    "value", ["127.0.0.1,::1", "10.0.0.0/8, 172.28.0.10", "*", "2001:db8::/32"]
)
def test_forwarded_allow_ips_accepts_addresses_networks_and_wildcard(
    value: str,
) -> None:
    assert Settings(forwarded_allow_ips=value).forwarded_allow_ips == value  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("value", ["10.0.0.0/33", "caddy", "1.2.3.4,", ""])
def test_forwarded_allow_ips_rejects_malformed_entries(value: str) -> None:
    with pytest.raises(ValidationError, match="FORWARDED_ALLOW_IPS"):
        Settings(forwarded_allow_ips=value)  # pyright: ignore[reportCallIssue]
