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


def _settings_without_env(monkeypatch, **overrides) -> Settings:
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    monkeypatch.delenv("SERVER_HOSTS", raising=False)
    required = {
        "database_url": "postgresql+asyncpg://u:p@localhost:5433/db",
        "allowed_origins": [],
        "jwt_secret_key": "test-only",
        "mail_from": "no-reply@example.com",
        "mail_port": 1025,
        "mail_server": "localhost",
        "mail_starttls": False,
        "mail_ssl_tls": False,
    }
    return Settings(_env_file=None, **(required | overrides))  # pyright: ignore[reportCallIssue]


def test_local_default_trusts_the_compose_caddy(monkeypatch) -> None:
    settings = _settings_without_env(monkeypatch, environment="local")

    assert settings.forwarded_allow_ips == "127.0.0.1,::1,172.28.0.10"


def test_production_default_trusts_only_loopback(monkeypatch) -> None:
    settings = _settings_without_env(monkeypatch, environment="production")

    assert settings.forwarded_allow_ips == "127.0.0.1,::1"


def test_an_explicit_trust_list_is_kept_as_given(monkeypatch) -> None:
    settings = _settings_without_env(
        monkeypatch, environment="local", forwarded_allow_ips="10.0.0.1"
    )

    assert settings.forwarded_allow_ips == "10.0.0.1"


def test_dev_server_listens_on_loopback_and_docker_bridge_by_default(
    monkeypatch,
) -> None:
    settings = _settings_without_env(monkeypatch)

    assert settings.server_host_list == ["127.0.0.1", "172.17.0.1"]


@pytest.mark.parametrize("value", ["localhost", "0.0.0.0/0", "127.0.0.1,"])
def test_server_hosts_rejects_non_addresses(monkeypatch, value: str) -> None:
    with pytest.raises(ValidationError, match="SERVER_HOSTS"):
        _settings_without_env(monkeypatch, server_hosts=value)
