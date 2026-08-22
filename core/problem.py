import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.exception import DomainException

logger = logging.getLogger(__name__)

DEFAULT_PROBLEM_TYPE = "about:blank"
PROBLEM_MEDIA_TYPE = "application/problem+json"


class InvalidParam(BaseModel):
    name: str = Field(
        ..., description="Field or parameter location that failed validation"
    )
    reason: str = Field(
        ..., description="Human-readable explanation of the validation failure"
    )
    code: str | None = Field(
        None, description="Validation rule code (e.g., value_error.email)"
    )


class ProblemDetails(BaseModel):
    type: str = Field(
        DEFAULT_PROBLEM_TYPE, description="URI reference identifying the problem type"
    )
    title: str = Field(
        ..., description="Short, human-readable summary of the problem type"
    )
    status: int = Field(..., description="HTTP status code")
    detail: str = Field(
        ..., description="Human-readable explanation specific to this occurrence"
    )
    instance: str = Field(
        ..., description="URI reference identifying the specific occurrence"
    )
    correlation_id: str | None = Field(
        None, description="Unique correlation or trace ID"
    )
    invalid_params: list[InvalidParam] | None = Field(
        None, description="Detailed list of field validation failures for 422 errors"
    )

    model_config = {
        "extra": "allow",
        "json_schema_extra": {
            "example": {
                "type": "https://api.example.com/errors/invalid-input",
                "title": "Unprocessable Entity",
                "status": 422,
                "detail": "Request validation failed",
                "instance": "/api/v1/auth/login",
                "correlation_id": "b1e1854f-dc8b-4e47-a1f5-d8e78464132a",
                "invalid_params": [
                    {"name": "email", "reason": "field required", "code": "missing"}
                ],
            }
        },
    }


def problem_response(
    request: Request,
    status: int,
    *,
    detail: str,
    type_uri: str = DEFAULT_PROBLEM_TYPE,
    title: str | None = None,
    headers: dict[str, str] | None = None,
    invalid_params: list[InvalidParam] | None = None,
    extensions: dict[str, Any] | None = None,
) -> JSONResponse:
    from core.middlewares.correlation import request_id_context

    correlation_id = request_id_context.get() or request.headers.get(
        "X-Request-ID", "-"
    )

    try:
        resolved_title = title or HTTPStatus(status).phrase
    except ValueError:
        resolved_title = "Error"

    problem = ProblemDetails(
        type=type_uri,
        title=resolved_title,
        status=status,
        detail=detail,
        instance=request.url.path,
        correlation_id=correlation_id,
        invalid_params=invalid_params,
    )

    payload = problem.model_dump(exclude_none=True)

    if extensions:
        payload.update(extensions)

    return JSONResponse(
        content=payload,
        status_code=status,
        headers=headers,
        media_type=PROBLEM_MEDIA_TYPE,
    )


async def domain_exception_handler(
    request: Request, exc: DomainException
) -> JSONResponse:
    return problem_response(
        request,
        exc.status_code,
        detail=exc.detail,
        type_uri=exc.type_str,
        title=exc.title,
        extensions=exc.extensions,
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return problem_response(request, exc.status_code, detail=detail)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    invalid_params = [
        InvalidParam(
            name=".".join(str(part) for part in error.get("loc", ()) if part != "body"),
            reason=error.get("msg"),
            code=error.get("type"),
        )
        for error in exc.errors()
    ]

    return problem_response(
        request,
        422,
        detail="Request validation failed",
        title="Unprocessable Entity",
        invalid_params=invalid_params,
    )


async def rate_limit_exception_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    response = problem_response(
        request,
        429,
        detail=f"Rate limit exceeded: {exc.detail}",
        title="Too Many Requests",
    )

    limiter = getattr(request.app.state, "limiter", None)
    if limiter is not None:
        current_limit = getattr(request.state, "view_rate_limit", None)
        response = limiter._inject_headers(response, current_limit)

    return response


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s", request.url.path)
    return problem_response(
        request,
        500,
        detail="Internal server error",
        title="Internal Server Error",
    )


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainException, domain_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(FastAPIHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]
