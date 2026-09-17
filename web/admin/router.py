from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi_pagination.cursor import CursorParams

from auth.dependencies import auth
from auth.services.security_service import SecurityService
from core.limiter import limiter
from user.dependencies import get_user_repository
from user.repositories.user_repository import UserRepository
from web.admin.dependencies import AdminGuard
from web.dependencies import templates

admin_router = APIRouter(prefix="/admin", tags=["Admin"], include_in_schema=False)

UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


@admin_router.get("/login", response_class=HTMLResponse)
async def admin_login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "admin/login.html", {})


@admin_router.post("/login")
@limiter.limit("5/minute")
async def admin_login_submit(
    request: Request,
    user_repo: UserRepositoryDep,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    user = await SecurityService.authenticate(email, password, user_repo)
    # Same generic error for wrong password and for a correct password with
    # no admin:read scope — telling them apart would let this form be used
    # to confirm a guessed password is valid, even without admin access.
    if user is None or "admin:read" not in user.scopes.split():
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {"error": "Invalid credentials"},
            status_code=401,
        )

    token = auth.create_access_token(uid=str(user.id), scopes=user.scopes.split())
    refresh_token = auth.create_refresh_token(uid=str(user.id))

    redirect = RedirectResponse("/admin/users", status_code=303)
    auth.set_access_cookies(token, redirect)
    auth.set_refresh_cookies(refresh_token, redirect)
    return redirect


@admin_router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request, user_repo: UserRepositoryDep, _guard: AdminGuard
):
    page = await user_repo.list(CursorParams())
    return templates.TemplateResponse(
        request, "admin/users.html", {"users": page.items, "cursor": page.next_page}
    )


@admin_router.get("/users/rows", response_class=HTMLResponse)
async def users_rows(
    request: Request,
    user_repo: UserRepositoryDep,
    _guard: AdminGuard,
    cursor: str | None = None,
):
    page = await user_repo.list(CursorParams(cursor=cursor))
    return templates.TemplateResponse(
        request,
        "admin/partials/user_row.html",
        {"users": page.items, "cursor": page.next_page},
    )
