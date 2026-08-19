import contextvars
import logging

from sqlalchemy import event
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.database import primary_engine, replica_engine
from core.problem import problem_response

logger = logging.getLogger(__name__)

_query_count: contextvars.ContextVar[int] = contextvars.ContextVar(
    "_query_count", default=0
)

DEFAULT_THRESHOLD = 10


def _increment_query_count(*args, **kwargs) -> None:
    _query_count.set(_query_count.get() + 1)


event.listen(
    primary_engine.sync_engine, "before_cursor_execute", _increment_query_count
)
event.listen(
    replica_engine.sync_engine, "before_cursor_execute", _increment_query_count
)


class N1DetectorMiddleware:
    _listeners_attached: bool = False

    def __init__(self, app: ASGIApp, threshold: int = DEFAULT_THRESHOLD) -> None:
        self.app = app
        self.threshold = threshold

        if not N1DetectorMiddleware._listeners_attached:
            event.listen(
                primary_engine.sync_engine,
                "before_cursor_execute",
                _increment_query_count,
            )
            event.listen(
                replica_engine.sync_engine,
                "before_cursor_execute",
                _increment_query_count,
            )
            N1DetectorMiddleware._listeners_attached = True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Pass non-HTTP protocols (e.g. WebSockets) straight through
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            # 1. Reset query counter for the current request
            token = _query_count.set(0)

            # 2. Intercept response start event to inject X-Query-Count header & inspect count
            async def send_with_query_count_header(message: Message) -> None:
                if message["type"] == "http.response.start":
                    count = _query_count.get()
                    mutable_headers = MutableHeaders(scope=message)
                    mutable_headers["X-Query-Count"] = str(count)

                    if count > self.threshold:
                        logger.warning(
                            "N+1 query alert",
                            extra={
                                "method": scope.get("method", ""),
                                "path": scope.get("path", ""),
                                "query_count": count,
                                "threshold": self.threshold,
                            },
                        )
                await send(message)

            try:
                # 3. Pass request down the ASGI stack
                await self.app(scope, receive, send_with_query_count_header)
            finally:
                # Always reset context variable, even if the request fails
                _query_count.reset(token)

        except Exception:
            # 4. Catch any middleware-level crash and return RFC 9457 Problem Details
            logger.exception("Unhandled exception in N1DetectorMiddleware")
            request = Request(scope)
            response = problem_response(
                request,
                500,
                detail="An internal server error occurred.",
                title="Internal Server Error",
            )
            await response(scope, receive, send)
