from uuid import UUID

from authx import TokenPayload
from fastapi import (
    APIRouter,
    Depends,
    Request,
    Response,
)
from fastapi_pagination.cursor import CursorPage, CursorParams

from auth.dependencies import auth, get_auth_service, get_auth_session
from auth.entities.auth_session import AuthSession
from auth.services.auth_service import AuthService
from core.limiter import limiter
from user.dependencies import get_current_user, get_user_service
from user.entities.user import User
from user.schemas.user_schema import (
    CreateUserRequest,
    UpdateUserRequest,
    UserResponse,
)
from user.services.user_service import UserService

user_router = APIRouter(prefix="/user", tags=["User"])


@user_router.post("/create", response_model=UserResponse)
@limiter.limit("5/minute")
async def create_user(
    data: CreateUserRequest,
    request: Request,
    service: UserService = Depends(get_user_service),
) -> User:
    return await service.register(data)


@user_router.get("/get", response_model=UserResponse)
async def get_user(
    user: User = Depends(get_current_user),
) -> User:
    return user


@user_router.patch("/update", response_model=UserResponse)
async def update_user(
    data: UpdateUserRequest,
    service: UserService = Depends(get_user_service),
    payload: TokenPayload = Depends(
        auth.token_required(type="access", locations=["headers"])
    ),
):
    return await service.update(UUID(payload.sub), data)


@user_router.delete("/delete")
async def delete_user(
    response: Response,
    service: AuthService = Depends(get_auth_service),
    session: AuthSession = Depends(get_auth_session),
):
    await service.close_account(session.user_id, session.tokens)

    auth.unset_refresh_cookies(response)
    return {"message": "User deleted"}


@user_router.get("/list", response_model=CursorPage[UserResponse])
async def list_users(
    params: CursorParams = Depends(),
    service: UserService = Depends(get_user_service),
    payload: TokenPayload = Depends(
        auth.token_required(type="access", locations=["headers"])
    ),
) -> CursorPage[User]:
    return await service.list(params)
