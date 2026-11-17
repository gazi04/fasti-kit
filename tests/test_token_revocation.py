import uuid

import pytest
from authx import TokenPayload

import auth.dependencies as auth_dependencies
from auth.blocklist import NullTokenBlocklist
from auth.dependencies import auth, is_token_revoked
from auth.entities.auth_session import TokenRef
from auth.repositories.revoked_token_repository import RevokedTokenRepository
from core.factories.user_factory import make_email
from core.setting import get_settings
from user.repositories.user_repository import UserRepository

ME_URL = "/api/v1/users/me"


@pytest.fixture(autouse=True)
def _database_only(monkeypatch):
    monkeypatch.setattr(auth_dependencies, "blocklist", NullTokenBlocklist())


def _token(user_id: uuid.UUID) -> str:
    return auth.create_access_token(uid=str(user_id))


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _ref_of(token: str) -> TokenRef:
    settings = get_settings()
    payload = TokenPayload.decode(
        token,
        key=settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        verify=True,
    )
    assert payload.jti is not None
    return TokenRef(payload.jti, payload.expiry_datetime)


async def test_null_blocklist_never_answers_and_never_loads() -> None:
    blocklist = NullTokenBlocklist()

    async def _load() -> list[TokenRef]:
        raise AssertionError("the null blocklist must not load revoked tokens")

    await blocklist.revoke([_ref_of(_token(uuid.uuid4()))])
    await blocklist.reseed(_load)

    assert await blocklist.lookup(uuid.uuid4().hex) is None


async def test_clean_token_is_checked_against_the_database(db) -> None:
    assert await is_token_revoked(_token(uuid.uuid4())) is False


async def test_revoked_token_is_found_in_the_database(db) -> None:
    token = _token(uuid.uuid4())
    ref = _ref_of(token)
    await RevokedTokenRepository(db).add(ref.jti, ref.expires_at)

    assert await is_token_revoked(token) is True


async def test_route_rejects_a_token_revoked_in_the_database(client, db) -> None:
    user = await UserRepository(db).add("Revoked", make_email(), "pw")
    token = _token(user.id)
    ref = _ref_of(token)
    await RevokedTokenRepository(db).add(ref.jti, ref.expires_at)

    response = await client.get(ME_URL, headers=_bearer(token))

    assert response.status_code == 401, response.text


async def test_logout_blocks_the_access_token(client, db) -> None:
    user = await UserRepository(db).add("Logout", make_email(), "pw")
    headers = _bearer(_token(user.id))

    logout = await client.post("/api/v1/auth/logout", headers=headers)
    assert logout.status_code == 200, logout.text

    again = await client.get(ME_URL, headers=headers)
    assert again.status_code == 401, again.text


async def test_token_check_opens_one_session(client, db, monkeypatch) -> None:
    user = await UserRepository(db).add("Session", make_email(), "pw")
    opened = {"count": 0}
    open_session = auth_dependencies.AsyncSessionLocal

    def _counting():
        opened["count"] += 1
        return open_session()

    monkeypatch.setattr(auth_dependencies, "AsyncSessionLocal", _counting)

    response = await client.get(ME_URL, headers=_bearer(_token(user.id)))

    assert response.status_code == 200, response.text
    assert opened["count"] == 1
