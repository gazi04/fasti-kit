"""
End-to-end tests for the auth flows that AuthService owns: verify-email,
reset-password, logout, account deletion and refresh. Each flow is one
repository transaction, so these check the committed outcome and the
single-use guarantee on the token.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from authx import TokenPayload
from sqlalchemy import select, update

import auth.dependencies as auth_dependencies
from auth.dependencies import auth
from auth.exceptions import InvalidCredentialsError
from auth.models import RefreshSessionModel, RevokedTokenModel
from auth.repositories.account_repository import AccountRepository
from auth.repositories.refresh_session_repository import RefreshSessionRepository
from auth.repositories.revoked_token_repository import RevokedTokenRepository
from auth.services.auth_service import AuthService
from auth.services.email_verification_service import EmailVerificationService
from auth.services.password_reset_service import PasswordResetService
from auth.services.security_service import SecurityService
from core.factories.user_factory import make_email
from core.limiter import limiter
from core.outbox.model import OutboxEvent
from core.setting import get_settings
from user.repositories.user_repository import UserRepository

VERIFY_URL = "/api/v1/auth/verify-email"
RESET_URL = "/api/v1/auth/reset-password"


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    limiter.enabled = False
    yield
    limiter.enabled = True


def _service(db, reuse_grace: timedelta = timedelta(seconds=10)) -> AuthService:
    return AuthService(
        UserRepository(db),
        AccountRepository(db),
        RevokedTokenRepository(db),
        RefreshSessionRepository(db),
        auth_dependencies.blocklist,
        session_ttl=timedelta(days=1),
        reuse_grace=reuse_grace,
    )


async def _unverified_user(db):
    repo = UserRepository(db)
    user = await repo.add(
        "Flow User", make_email(), await SecurityService.hash_password("pw")
    )
    token, jti = EmailVerificationService.create_verification_token(str(user.id))
    await repo.update(user.id, pending_verification_jti=jti)
    return user, token, jti


async def _user_awaiting_reset(db):
    repo = UserRepository(db)
    user = await repo.add(
        "Reset User", make_email(), await SecurityService.hash_password("old")
    )
    token, jti = PasswordResetService.create_reset_token(str(user.id))
    await repo.update(user.id, pending_password_reset_jti=jti, is_verified=True)
    return user, token, jti


def _bearer(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth.create_access_token(uid=str(user_id))}"}


async def test_verify_email_marks_user_verified_and_burns_the_token(client, db) -> None:
    user, token, jti = await _unverified_user(db)

    response = await client.get(VERIFY_URL, params={"token": token})

    assert response.status_code == 200, response.text
    verified = await UserRepository(db).get(user.id)
    assert verified is not None and verified.is_verified is True
    assert await RevokedTokenRepository(db).exists(jti) is True


async def test_verify_email_rejects_a_reused_link(client, db) -> None:
    _, token, _ = await _unverified_user(db)
    await client.get(VERIFY_URL, params={"token": token})

    response = await client.get(VERIFY_URL, params={"token": token})

    assert response.status_code == 400
    assert response.json()["detail"] == "Verification link already used"


async def test_verify_email_rejects_a_superseded_link(client, db) -> None:
    user, token, _ = await _unverified_user(db)
    await UserRepository(db).update(user.id, pending_verification_jti="newer")

    response = await client.get(VERIFY_URL, params={"token": token})

    assert response.status_code == 400
    assert "superseded" in response.json()["detail"]
    unchanged = await UserRepository(db).get(user.id)
    assert unchanged is not None and unchanged.is_verified is False


async def test_verify_email_rejects_garbage_and_wrong_type_tokens(client, db) -> None:
    garbage = await client.get(VERIFY_URL, params={"token": "not-a-jwt"})
    assert garbage.status_code == 400

    user, _, _ = await _unverified_user(db)
    reset_token, _ = PasswordResetService.create_reset_token(str(user.id))
    wrong_type = await client.get(VERIFY_URL, params={"token": reset_token})
    assert wrong_type.status_code == 400
    assert wrong_type.json()["detail"] == "Invalid verification token"


async def test_verify_email_for_unknown_user_is_404(client) -> None:
    token, _ = EmailVerificationService.create_verification_token(str(uuid.uuid4()))

    response = await client.get(VERIFY_URL, params={"token": token})

    assert response.status_code == 404


async def test_reset_password_changes_hash_and_burns_the_token(client, db) -> None:
    user, token, jti = await _user_awaiting_reset(db)

    response = await client.post(
        RESET_URL, json={"token": token, "new_password": "brand-new-pw"}
    )

    assert response.status_code == 200, response.text
    updated = await UserRepository(db).get(user.id)
    assert updated is not None
    assert await SecurityService.check_password("brand-new-pw", updated.password_hash)
    assert await RevokedTokenRepository(db).exists(jti) is True


async def test_reset_password_rejects_a_reused_link(client, db) -> None:
    _, token, _ = await _user_awaiting_reset(db)
    await client.post(RESET_URL, json={"token": token, "new_password": "first-new-pw"})

    response = await client.post(
        RESET_URL, json={"token": token, "new_password": "second-new-pw"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Reset link already used"


async def test_reset_password_rejects_a_deactivated_user(client, db) -> None:
    user, token, _ = await _user_awaiting_reset(db)
    await UserRepository(db).delete(user.id)

    response = await client.post(
        RESET_URL, json={"token": token, "new_password": "brand-new-pw"}
    )

    assert response.status_code == 404


async def test_reset_password_rejects_an_expired_token(client, db) -> None:
    user, _, jti = await _user_awaiting_reset(db)
    settings = get_settings()
    past = datetime.now(UTC) - timedelta(minutes=1)
    expired = jwt.encode(
        {
            "sub": str(user.id),
            "type": "password_reset",
            "jti": jti,
            "iat": past - timedelta(minutes=15),
            "exp": past,
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = await client.post(
        RESET_URL, json={"token": expired, "new_password": "brand-new-pw"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired reset link"


async def test_logout_revokes_the_access_token(client, db) -> None:
    user = await UserRepository(db).add("Logout User", make_email(), "pw")
    headers = _bearer(user.id)

    first = await client.post("/api/v1/auth/logout", headers=headers)
    assert first.status_code == 200, first.text

    rows = (await db.scalars(select(RevokedTokenModel))).all()
    assert len(rows) == 1

    second = await client.post("/api/v1/auth/logout", headers=headers)
    assert second.status_code in (401, 403, 422)


async def test_delete_user_deactivates_and_revokes_in_one_step(client, db) -> None:
    user = await UserRepository(db).add("Delete Me", make_email(), "pw")
    headers = _bearer(user.id)

    response = await client.delete("/api/v1/users/me", headers=headers)

    assert response.status_code == 200, response.text
    gone = await UserRepository(db).get(user.id)
    assert gone is not None and gone.is_active is False
    assert len((await db.scalars(select(RevokedTokenModel))).all()) == 1


async def test_delete_user_for_unknown_user_is_404(client, db) -> None:
    response = await client.delete("/api/v1/users/me", headers=_bearer(uuid.uuid4()))

    assert response.status_code == 404
    assert (await db.scalars(select(RevokedTokenModel))).all() == []


async def test_create_user_then_update_conflict_is_409(client, db) -> None:
    taken = make_email()
    await UserRepository(db).add("Taken", taken, "pw")
    other = await UserRepository(db).add("Other", make_email(), "pw")

    response = await client.patch(
        "/api/v1/users/me", json={"email": taken}, headers=_bearer(other.id)
    )

    assert response.status_code == 409


async def test_resend_and_forgot_write_exactly_one_outbox_row_each(client, db) -> None:
    unverified = await UserRepository(db).add("Resend", make_email(), "pw")

    await client.post(
        "/api/v1/auth/resend-verification", json={"email": unverified.email}
    )
    await client.post("/api/v1/auth/forgot-password", json={"email": unverified.email})

    subjects = sorted(
        row.payload["subject"] for row in (await db.scalars(select(OutboxEvent))).all()
    )
    assert subjects == ["Reset your password", "Verify your email"]
    refreshed = await UserRepository(db).get(unverified.id)
    assert refreshed is not None
    assert refreshed.pending_verification_jti is not None
    assert refreshed.pending_password_reset_jti is not None


async def test_service_refresh_requires_an_active_verified_user(db) -> None:
    repo = UserRepository(db)
    user = await repo.add("Refresh", make_email(), "pw")
    service = _service(db)
    session = await RefreshSessionRepository(db).create(
        user.id, datetime.now(UTC) + timedelta(days=1)
    )

    with pytest.raises(InvalidCredentialsError):
        await service.refresh(user.id, session.id, 0)

    await repo.update(user.id, is_verified=True)
    refreshed, rotated = await service.refresh(user.id, session.id, 0)
    assert refreshed.id == user.id
    assert rotated.generation == 1

    await repo.delete(user.id)
    with pytest.raises(InvalidCredentialsError):
        await service.refresh(user.id, session.id, 1)

    with pytest.raises(InvalidCredentialsError):
        await service.refresh(uuid.uuid4(), session.id, 1)


# ---------------------------------------------------------------------------
# POST /auth/refresh over HTTP: refresh cookie, CSRF check, blocklist
# ---------------------------------------------------------------------------

LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
REFRESH_COOKIE = auth.config.JWT_REFRESH_COOKIE_NAME
CSRF_COOKIE = auth.config.JWT_REFRESH_CSRF_COOKIE_NAME
CSRF_HEADER = auth.config.JWT_REFRESH_CSRF_HEADER_NAME


async def _log_in(client, db):
    repo = UserRepository(db)
    user = await repo.add(
        "Refresh User", make_email(), await SecurityService.hash_password("pw")
    )
    await repo.update(user.id, is_verified=True)

    response = await client.post(
        LOGIN_URL, json={"email": user.email, "password": "pw"}
    )
    assert response.status_code == 200, response.text
    return user, response


def _keep_refresh_cookies(client, login_response) -> str:
    refresh_token = login_response.cookies[REFRESH_COOKIE]
    csrf = login_response.cookies[CSRF_COOKIE]
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, refresh_token)
    client.cookies.set(CSRF_COOKIE, csrf)
    return csrf


def _decode(token: str) -> TokenPayload:
    settings = get_settings()
    return TokenPayload.decode(
        token,
        key=settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        verify=True,
    )


async def test_refresh_issues_a_working_access_token(client, db) -> None:
    user, login = await _log_in(client, db)
    csrf = _keep_refresh_cookies(client, login)

    response = await client.post(REFRESH_URL, headers={CSRF_HEADER: csrf})

    assert response.status_code == 200, response.text
    access_token = response.json()["access_token"]
    payload = _decode(access_token)
    assert payload.sub == str(user.id)
    assert payload.type == "access"
    assert payload.scopes == user.scope_list

    me = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["id"] == str(user.id)


async def test_refresh_picks_up_scopes_granted_after_login(client, db) -> None:
    user, login = await _log_in(client, db)
    csrf = _keep_refresh_cookies(client, login)
    await UserRepository(db).update(user.id, scopes="admin:read")

    response = await client.post(REFRESH_URL, headers={CSRF_HEADER: csrf})

    assert response.status_code == 200, response.text
    assert _decode(response.json()["access_token"]).scopes == ["admin:read"]


async def test_refresh_requires_the_csrf_header(client, db) -> None:
    _, login = await _log_in(client, db)
    _keep_refresh_cookies(client, login)

    response = await client.post(REFRESH_URL)

    assert response.status_code == 401, response.text
    assert response.json()["detail"].startswith("Missing CSRF token")


async def test_refresh_rejects_a_mismatched_csrf_header(client, db) -> None:
    _, login = await _log_in(client, db)
    _keep_refresh_cookies(client, login)

    response = await client.post(REFRESH_URL, headers={CSRF_HEADER: "forged"})

    assert response.status_code == 401, response.text
    assert response.json()["detail"].startswith("CSRF token mismatch")


async def test_refresh_ignores_an_access_token_in_the_header(client, db) -> None:
    _, login = await _log_in(client, db)
    client.cookies.clear()

    response = await client.post(
        REFRESH_URL,
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )

    assert response.status_code == 401, response.text
    assert response.json()["detail"].startswith("Missing cookie")


async def test_refresh_rejects_a_token_revoked_by_logout(client, db) -> None:
    _, login = await _log_in(client, db)
    csrf = _keep_refresh_cookies(client, login)
    logout = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert logout.status_code == 200, logout.text
    _keep_refresh_cookies(client, login)

    response = await client.post(REFRESH_URL, headers={CSRF_HEADER: csrf})

    assert response.status_code == 401, response.text
    assert response.json()["detail"].startswith("Token has been revoked")


async def test_refresh_rejects_a_user_deactivated_after_login(client, db) -> None:
    user, login = await _log_in(client, db)
    csrf = _keep_refresh_cookies(client, login)
    await UserRepository(db).delete(user.id)

    response = await client.post(REFRESH_URL, headers={CSRF_HEADER: csrf})

    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "Invalid credentials"


# ---------------------------------------------------------------------------
# Refresh-token rotation: one session per login, a new cookie per refresh,
# and a replayed old cookie revokes the session unless it is a tab race.
# ---------------------------------------------------------------------------


async def _refresh_with(client, response):
    csrf = _keep_refresh_cookies(client, response)
    return await client.post(REFRESH_URL, headers={CSRF_HEADER: csrf})


def _refresh_payload(response) -> TokenPayload:
    return _decode(response.cookies[REFRESH_COOKIE])


def _session_claims(response) -> dict:
    return _refresh_payload(response).model_extra or {}


async def _age_last_rotation(db, session_id: str) -> None:
    await db.execute(
        update(RefreshSessionModel)
        .where(RefreshSessionModel.id == uuid.UUID(session_id))
        .values(rotated_at=datetime.now(UTC) - timedelta(minutes=5))
    )


async def test_refresh_rotates_the_cookie_without_extending_the_session(
    client, db
) -> None:
    _, login = await _log_in(client, db)
    first = _refresh_payload(login)

    rotated = await _refresh_with(client, login)
    assert rotated.status_code == 200, rotated.text
    second = _refresh_payload(rotated)

    assert _session_claims(rotated) == {"sid": _session_claims(login)["sid"], "gen": 1}
    assert second.jti != first.jti
    assert second.exp == first.exp

    again = await _refresh_with(client, rotated)
    assert again.status_code == 200, again.text
    assert _session_claims(again)["gen"] == 2


async def test_refresh_replay_within_grace_is_a_conflict_not_a_revoke(
    client, db
) -> None:
    _, login = await _log_in(client, db)
    rotated = await _refresh_with(client, login)
    assert rotated.status_code == 200, rotated.text

    replay = await _refresh_with(client, login)
    assert replay.status_code == 409, replay.text
    assert replay.json()["type"] == "errors/conflict"

    latest = await _refresh_with(client, rotated)
    assert latest.status_code == 200, latest.text


async def test_refresh_replay_after_grace_revokes_the_whole_session(client, db) -> None:
    _, login = await _log_in(client, db)
    rotated = await _refresh_with(client, login)
    assert rotated.status_code == 200, rotated.text
    await _age_last_rotation(db, _session_claims(rotated)["sid"])

    replay = await _refresh_with(client, login)
    assert replay.status_code == 401, replay.text
    assert replay.json()["type"] == "errors/invalid-refresh-token"

    latest = await _refresh_with(client, rotated)
    assert latest.status_code == 401, latest.text
    assert latest.json()["detail"] == "Refresh token is no longer valid"


async def test_refresh_rejects_a_token_issued_before_sessions(client, db) -> None:
    user, _ = await _log_in(client, db)
    legacy = auth.create_refresh_token(uid=str(user.id))
    csrf = _decode(legacy).csrf
    assert csrf is not None
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, legacy)
    client.cookies.set(CSRF_COOKIE, csrf)

    response = await client.post(REFRESH_URL, headers={CSRF_HEADER: csrf})

    assert response.status_code == 401, response.text
    assert response.json()["type"] == "errors/invalid-refresh-token"


async def _session_of(db, response) -> RefreshSessionModel:
    session_id = uuid.UUID(_session_claims(response)["sid"])
    model = await db.get(RefreshSessionModel, session_id, populate_existing=True)
    assert model is not None
    return model


async def test_logout_revokes_the_refresh_session(client, db) -> None:
    _, login = await _log_in(client, db)
    _keep_refresh_cookies(client, login)

    logout = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )

    assert logout.status_code == 200, logout.text
    assert (await _session_of(db, login)).revoked_at is not None


async def test_reset_password_revokes_every_refresh_session(client, db) -> None:
    user, token, _ = await _user_awaiting_reset(db)
    sessions = RefreshSessionRepository(db)
    expiry = datetime.now(UTC) + timedelta(days=1)
    first = await sessions.create(user.id, expiry)
    second = await sessions.create(user.id, expiry)

    response = await client.post(
        RESET_URL, json={"token": token, "new_password": "brand-new-pw"}
    )

    assert response.status_code == 200, response.text
    for session in (first, second):
        stored = await sessions.get(session.id)
        assert stored is not None and stored.revoked_at is not None


async def test_delete_user_revokes_every_refresh_session(client, db) -> None:
    _, login = await _log_in(client, db)

    response = await client.delete(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )

    assert response.status_code == 200, response.text
    assert (await _session_of(db, login)).revoked_at is not None
