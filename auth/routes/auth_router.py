from typing import AsyncGenerator

from authx import JWTDecodeError, TokenPayload
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from auth.dependencies import auth
from auth.repositories.revoked_token_repository import RevokedTokenRepository
from auth.schemas.auth_schema import LoginRequest, LoginResponse
from auth.services.security_service import SecurityService
from core.limiter import limiter
from core.database import get_db
from user.repositories.user_repository import UserRepository

auth_router = APIRouter(prefix='/auth', tags=['Auth'])

@auth_router.post('/login')
@limiter.limit('5/minute')
async def login(data: LoginRequest, request: Request, response: Response, db: AsyncGenerator = Depends(get_db)) -> LoginResponse:
    user = await UserRepository(db).get_by_email(data.email)

    if user is None or not SecurityService.check_password(data.password, user.password_hash):
        raise HTTPException(401, detail='Invalid credentials')

    token = auth.create_access_token(uid=str(user.id))
    refresh_token = auth.create_refresh_token(uid=str(user.id))
    
    auth.set_refresh_cookies(refresh_token, response)

    return LoginResponse(access_token=token)


@auth_router.get('/protected')
async def protected(payload: TokenPayload = Depends(auth.token_required(type='access', locations=['headers']))):
    return {'user': payload.sub}


@auth_router.post('/refresh')
async def refresh(payload: TokenPayload = Depends(auth.token_required(type='refresh', locations=['cookies']))) -> LoginResponse:
    new_access_token = auth.create_access_token(uid=payload.sub)
    return LoginResponse(access_token=new_access_token)


@auth_router.post('/logout')
async def logout(request: Request, response: Response, payload: TokenPayload = Depends(auth.token_required(type='access', locations=['headers'])), db: AsyncGenerator = Depends(get_db)) -> dict:
    repo = RevokedTokenRepository(db)
    await repo.add(payload.jti, payload.expiry_datetime)

    refresh_token = request.cookies.get(auth.config.JWT_REFRESH_COOKIE_NAME)
    
    if refresh_token:
        try:
            refresh_payload = TokenPayload.decode(refresh_token, key=auth.config.JWT_SECRET_KEY, algorithms=[auth.config.JWT_ALGORITHM], verify=False)
            await repo.add(refresh_payload.jti, refresh_payload.expiry_datetime)
        except JWTDecodeError:
            pass

    auth.unset_refresh_cookies(response)
    return {'message': 'Logged out'}
