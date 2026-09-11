import contextvars
import logging
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.problem import problem_response

logger = logging.getLogger(__name__)

request_id_context = contextvars.ContextVar("request_id", default="-")


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            # 1. Extract or generate Correlation ID from raw headers
            headers = Headers(scope=scope)
            request_id = headers.get("X-Request-ID") or str(uuid.uuid4())
            token = request_id_context.set(request_id)

            # 2. Intercept response start event to inject X-Request-ID header
            async def send_with_correlation_header(message: Message) -> None:
                if message["type"] == "http.response.start":
                    mutable_headers = MutableHeaders(scope=message)
                    mutable_headers["X-Request-ID"] = request_id
                await send(message)

            try:
                # 3. Pass request down the ASGI stack
                await self.app(scope, receive, send_with_correlation_header)
            finally:
                # Always reset context variable, even if downstream route fails
                request_id_context.reset(token)

        except Exception:
            # 4. Catch any middleware-level crash and return RFC 9457 Problem Details
            logger.exception("Unhandled exception in CorrelationIdMiddleware")
            request = Request(scope)
            response = problem_response(
                request,
                500,
                detail="Internal server error",
                title="Internal Server Error",
            )
            await response(scope, receive, send)
