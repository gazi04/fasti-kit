import asyncio
import contextlib

from auth.services.security_service import SecurityService


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
