# src/core/middlewares/correlation.py
import contextvars
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

request_id_context = contextvars.ContextVar("request_id", default="-")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Extract or generate the ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        # Set the context variable for the current async task execution
        token = request_id_context.set(request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        # Reset the context variable
        request_id_context.reset(token)
        return response
