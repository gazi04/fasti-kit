from typing import Annotated

from authx import TokenPayload
from authx.exceptions import AuthXException
from fastapi import Depends, Request

from auth.dependencies import auth


class AdminRedirect(Exception):
    pass


async def admin_page_guard(request: Request) -> None:
    try:
        payload: TokenPayload = await auth.token_required(
            type="access", locations=["cookies"]
        )(request)
    except AuthXException as err:
        raise AdminRedirect from err

    if not payload.has_scopes("admin:read"):
        raise AdminRedirect


AdminGuard = Annotated[None, Depends(admin_page_guard)]
