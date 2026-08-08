import contextvars
import logging
from collections.abc import Callable

from fastapi import Request, Response
from sqlalchemy import event
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from core.database import engine

logger = logging.getLogger(__name__)

_query_count: contextvars.ContextVar[int] = contextvars.ContextVar(
    "_query_count", default=0
)

DEFAULT_THRESHOLD = 10


def _increment_query_count(*args, **kwargs) -> None:
    _query_count.set(_query_count.get() + 1)


event.listen(engine.sync_engine, "before_cursor_execute", _increment_query_count)


class N1DetectorMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, threshold: int = DEFAULT_THRESHOLD) -> None:
        super().__init__(app)
        self.threshold = threshold

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        token = _query_count.set(0)

        try:
            response = await call_next(request)

            count = _query_count.get()
            response.headers["X-Query-Count"] = str(count)

            if count > self.threshold:
                logger.warning(
                    "N+1 query alert",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "query_count": count,
                        "threshold": self.threshold,
                    },
                )

            return response
        finally:
            _query_count.reset(token)
