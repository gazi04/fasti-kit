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
from sqlalchemy import select

from auth.dependencies import auth
from auth.exceptions import InvalidCredentialsError
from auth.models import RevokedTokenModel
from auth.repositories.account_repository import AccountRepository
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


def _service(db) -> AuthService:
    return AuthService(
        UserRepository(db), AccountRepository(db), RevokedTokenRepository(db)
    )


async def _unverified_user(db):
    repo = UserRepository(db)
    user = await repo.add(
        "Flow User", make_email(), SecurityService.hash_password("pw")
    )
    token, jti = EmailVerificationService.create_verification_token(str(user.id))
    await repo.update(user.id, pending_verification_jti=jti)
    return user, token, jti


async def _user_awaiting_reset(db):
    repo = UserRepository(db)
    user = await repo.add(
        "Reset User", make_email(), SecurityService.hash_password("old")
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
    assert SecurityService.check_password("brand-new-pw", updated.password_hash)
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

    with pytest.raises(InvalidCredentialsError):
        await service.refresh(user.id)

    await repo.update(user.id, is_verified=True)
    refreshed = await service.refresh(user.id)
    assert refreshed.id == user.id

    await repo.delete(user.id)
    with pytest.raises(InvalidCredentialsError):
        await service.refresh(user.id)

    with pytest.raises(InvalidCredentialsError):
        await service.refresh(uuid.uuid4())
