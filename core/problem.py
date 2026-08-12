import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.exception import DomainException
from core.middlewares.correlation import request_id_context

logger = logging.getLogger(__name__)

DEFAULT_PROBLEM_TYPE = "about:blank"


def problem_response(
    request: Request,
    status: int,
    *,
    detail: str,
    type_uri: str = DEFAULT_PROBLEM_TYPE,
    title: str | None = None,
    headers: dict[str, str] | None = None,
    extensions: dict[str, Any] | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {
        "type": type_uri,
        "title": title or HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "correlation_id": request_id_context.get()
        or request.headers.get("X-Request-ID", "-"),
    }

    if extensions:
        content.update(extensions)

    return JSONResponse(
        content,
        status_code=status,
        headers=headers,
        media_type="application/problem+json",
    )


async def domain_exception_handler(
    request: Request, exc: DomainException
) -> JSONResponse:
    return problem_response(
        request, exc.status_code, detail=exc.detail, type_uri=exc.type_str
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return problem_response(request, exc.status_code, detail=detail)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ())),
            "message": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]

    return problem_response(
        request, 422, detail="Request validation failed", extensions={"errors": errors}
    )


async def rate_limit_exception_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    response = problem_response(
        request,
        429,
        detail=f"Rate limit exceeded: {exc.detail}",
        title="Too Many Request",
    )

    limiter = getattr(request.app.state, "limiter", None)
    if limiter is not None:
        current_limit = getattr(request.state, "view_rate_limit", None)
        response = limiter._inject_headers(response, current_limit)

    return response


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s", request.url.path)
    return problem_response(
        request, 500, detail="Internal server error", title="Internal Server Error"
    )


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainException, domain_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(FastAPIHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]
