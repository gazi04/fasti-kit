import asyncio
import contextlib

import pytest

from auth.services.security_service import SecurityService
from core.factories.user_factory import make_email
from user.repositories.user_repository import UserRepository


async def test_hash_and_check_round_trip() -> None:
    hashed = await SecurityService.hash_password("correct")

    assert await SecurityService.check_password("correct", hashed)
    assert not await SecurityService.check_password("wrong", hashed)


async def test_hashing_leaves_the_event_loop_free() -> None:
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    ticker = asyncio.create_task(tick())
    try:
        await SecurityService.hash_password("pw")
    finally:
        ticker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ticker

    assert ticks > 5


@pytest.mark.parametrize("known_email", [True, False])
async def test_authenticate_releases_the_primary_before_hashing(
    db, monkeypatch, known_email
) -> None:
    repo = UserRepository(db)
    email = make_email()
    if known_email:
        await repo.add("Release", email, await SecurityService.hash_password("pw"))

    in_transaction_while_hashing = []
    check_password = SecurityService.check_password

    async def recording_check(password: str, hashed_password: str) -> bool:
        in_transaction_while_hashing.append(db.in_transaction())
        return await check_password(password, hashed_password)

    monkeypatch.setattr(SecurityService, "check_password", recording_check)

    await SecurityService.authenticate(email, "pw", repo)

    assert in_transaction_while_hashing == [False]
