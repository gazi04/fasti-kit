from collections.abc import Awaitable, Callable, Iterable
from typing import Protocol

from auth.entities.auth_session import TokenRef

LoadRevoked = Callable[[], Awaitable[list[TokenRef]]]


class TokenBlocklist(Protocol):
    async def revoke(self, tokens: Iterable[TokenRef]) -> None: ...

    async def lookup(self, jti: str) -> bool | None: ...

    async def reseed(self, load: LoadRevoked) -> None: ...


class NullTokenBlocklist:
    async def revoke(self, tokens: Iterable[TokenRef]) -> None:
        return None

    async def lookup(self, jti: str) -> bool | None:
        return None

    async def reseed(self, load: LoadRevoked) -> None:
        return None
