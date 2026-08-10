from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute


class DeprecationRoute(APIRoute):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.deprecation_meta: dict[str, str | None] | None = getattr(
            self.endpoint, "__deprecation__", None
        )

        if getattr(self.endpoint, "__deprecation__", None) is not None:
            self.deprecated = True

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()
        meta = getattr(self.endpoint, "__deprecation__", None)

        if meta is None:
            return original

        async def handler(request: Request) -> Response:
            response = await original(request)
            response.headers["Deprecation"] = "true"

            if meta.get("sunset"):
                response.headers["sunset"] = meta["sunset"]  # type: ignore[arg-type]

            return response

        return handler


def deprecated(*, sunset: str | None = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        func.__deprecation__ = {"sunset": sunset}  # type: ignore
        return func

    return decorator
