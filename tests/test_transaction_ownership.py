"""
The repository owns the transaction: one public repository method is one
commit, and nothing above it commits. The shared test connection makes
uncommitted writes visible to later reads, so these tests count commits and
rollbacks directly instead.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from auth.repositories.account_repository import AccountRepository
from auth.repositories.revoked_token_repository import RevokedTokenRepository
from auth.services.auth_service import AuthService
from auth.services.email_verification_service import EmailVerificationService
from core.database import transaction
from core.exception import ConflictError
from core.factories.user_factory import make_email
from user.repositories.user_repository import UserRepository
from user.schemas.user_schema import CreateUserRequest
from user.services.user_service import UserService


@pytest.fixture
def counts(db, monkeypatch):
    calls = {"commit": 0, "rollback": 0}
    commit, rollback = db.commit, db.rollback

    async def counting_commit():
        calls["commit"] += 1
        await commit()

    async def counting_rollback():
        calls["rollback"] += 1
        await rollback()

    monkeypatch.setattr(db, "commit", counting_commit)
    monkeypatch.setattr(db, "rollback", counting_rollback)
    return calls


async def test_transaction_commits_on_success(db, counts) -> None:
    async with transaction(db):
        pass

    assert counts == {"commit": 1, "rollback": 0}


async def test_transaction_rolls_back_and_reraises_on_failure(db, counts) -> None:
    with pytest.raises(RuntimeError):
        async with transaction(db):
            raise RuntimeError("boom")

    assert counts == {"commit": 0, "rollback": 1}


async def test_each_repository_write_is_one_commit(db, counts) -> None:
    repo = UserRepository(db)

    user = await repo.add("Owner", make_email(), "pw")
    assert counts["commit"] == 1

    await repo.update(user.id, full_name="Owner Two")
    assert counts["commit"] == 2

    await repo.delete(user.id)
    assert counts["commit"] == 3


async def test_a_failed_repository_write_rolls_back_without_committing(
    db, counts
) -> None:
    repo = UserRepository(db)
    email = make_email()
    await repo.add("First", email, "pw")
    counts["commit"] = 0

    with pytest.raises(ConflictError):
        await repo.add("Second", email, "pw")

    assert counts == {"commit": 0, "rollback": 1}


async def test_register_writes_user_and_outbox_in_a_single_commit(db, counts) -> None:
    service = UserService(UserRepository(db))

    await service.register(
        CreateUserRequest(name="One Commit", email=make_email(), password="pw123456")
    )

    assert counts == {"commit": 1, "rollback": 0}


async def test_account_operations_are_a_single_commit_each(db, counts) -> None:
    user = await UserRepository(db).add("Accounts", make_email(), "pw")
    accounts = AccountRepository(db)
    expiry = datetime.now(UTC) + timedelta(hours=1)
    counts["commit"] = 0

    await accounts.verify_email(user.id, uuid.uuid4().hex, expiry)
    assert counts["commit"] == 1

    await accounts.reset_password(user.id, "hash", uuid.uuid4().hex, expiry)
    assert counts["commit"] == 2

    await accounts.start_email_verification(user.id, uuid.uuid4().hex, {"subject": "s"})
    assert counts["commit"] == 3

    await accounts.start_password_reset(user.id, uuid.uuid4().hex, {"subject": "s"})
    assert counts["commit"] == 4


async def test_service_flow_produces_exactly_the_repositorys_commit(db, counts) -> None:
    user_repo = UserRepository(db)
    user = await user_repo.add("Service", make_email(), "pw")
    token, jti = EmailVerificationService.create_verification_token(str(user.id))
    await user_repo.update(user.id, pending_verification_jti=jti)
    service = AuthService(user_repo, AccountRepository(db), RevokedTokenRepository(db))
    counts["commit"] = 0

    await service.verify_email(token)

    assert counts == {"commit": 1, "rollback": 0}
