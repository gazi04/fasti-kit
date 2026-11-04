from datetime import UTC, datetime, timedelta

from auth.repositories.refresh_session_repository import RefreshSessionRepository
from core.factories.user_factory import make_email
from user.repositories.user_repository import UserRepository


async def _session(db, expires_in: timedelta = timedelta(days=1)):
    user = await UserRepository(db).add("Sessions", make_email(), "pw")
    repo = RefreshSessionRepository(db)
    return repo, await repo.create(user.id, datetime.now(UTC) + expires_in)


async def test_rotate_succeeds_once_per_generation(db) -> None:
    repo, session = await _session(db)

    rotated = await repo.rotate(session.id, session.user_id, 0)
    assert rotated is not None
    assert rotated.generation == 1
    assert rotated.rotated_at is not None

    assert await repo.rotate(session.id, session.user_id, 0) is None


async def test_rotate_refuses_revoked_expired_and_foreign_sessions(db) -> None:
    repo, session = await _session(db)
    _, expired = await _session(db, expires_in=timedelta(seconds=-1))

    assert await repo.rotate(session.id, expired.user_id, 0) is None
    assert await repo.rotate(expired.id, expired.user_id, 0) is None

    await repo.revoke(session.id)
    assert await repo.rotate(session.id, session.user_id, 0) is None


async def test_revoke_is_idempotent(db) -> None:
    repo, session = await _session(db)

    await repo.revoke(session.id)
    first = await repo.get(session.id)
    await repo.revoke(session.id)
    second = await repo.get(session.id)

    assert first is not None and second is not None
    assert first.revoked_at is not None
    assert second.revoked_at == first.revoked_at


async def test_purge_expired_keeps_live_sessions(db) -> None:
    repo, live = await _session(db)
    _, expired = await _session(db, expires_in=timedelta(seconds=-1))

    assert await repo.purge_expired() == 1

    assert await repo.get(live.id) is not None
    assert await repo.get(expired.id) is None
