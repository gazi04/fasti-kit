from authx import exceptions as authx_exc
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.problem import problem_response

# Most-specific-first: JWTDecodeError covers its TokenExpired/etc. subclasses.
_AUTHX_STATUS: list[tuple[type[authx_exc.AuthXException], int]] = [
    (authx_exc.JWTDecodeError, 422),
    (authx_exc.InsufficientScopeError, 403),
    (authx_exc.PolicyDeniedError, 403),
    (authx_exc.PolicyEvaluationError, 500),
    (authx_exc.RateLimitExceeded, 429),
]
_DEFAULT_AUTHX_STATUS = 401


def _authx_status(exc: authx_exc.AuthXException) -> int:
    for exc_type, status in _AUTHX_STATUS:
        if isinstance(exc, exc_type):
            return status
    return _DEFAULT_AUTHX_STATUS


async def authx_exception_handler(
    request: Request, exc: authx_exc.AuthXException
) -> JSONResponse:
    return problem_response(request, _authx_status(exc), detail=str(exc))


def install_auth_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(authx_exc.AuthXException, authx_exception_handler)  # type: ignore[arg-type]
