from fastapi import FastAPI, Request
from fastapi.responses import Response

from core.exception import DomainException
from core.middlewares.correlation import request_id_context
from core.problem import domain_exception_handler
from web.dependencies import templates


async def admin_domain_exception_handler(
    request: Request, exc: DomainException
) -> Response:
    if not request.url.path.startswith("/admin/"):
        return await domain_exception_handler(request, exc)

    template = (
        "admin/partials/error.html"
        if request.headers.get("HX-Request") == "true"
        else "admin/error.html"
    )
    return templates.TemplateResponse(
        request,
        template,
        {
            "detail": exc.detail,
            "title": exc.title or "Error",
            "correlation_id": request_id_context.get(),
        },
        status_code=exc.status_code,
    )


def install_admin_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainException, admin_domain_exception_handler)  # type: ignore[arg-type]
