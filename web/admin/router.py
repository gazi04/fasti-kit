from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi_pagination.cursor import CursorParams

from user.dependencies import get_user_repository
from user.repositories.user_repository import UserRepository
from web.admin.dependencies import AdminGuard
from web.dependencies import templates

admin_router = APIRouter(prefix="/admin", tags=["Admin"], include_in_schema=False)

UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


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
