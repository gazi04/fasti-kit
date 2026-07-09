from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException

from auth.dependencies import auth
from auth.schemas.auth_schema import LoginRequest, LoginResponse
from auth.services.security_service import SecurityService
from core.database import get_db
from user.repositories.user_repository import UserRepository

auth_router = APIRouter(prefix='/auth', tags=['Auth'])

@auth_router.post('/login')
async def login(data: LoginRequest, db: AsyncGenerator = Depends(get_db)):
    user = await UserRepository(db).get_by_email(data.email)

    if user is None or not SecurityService.check_password(data.password, user.password_hash):
        raise HTTPException(401, detail='Invalid credentials')

    token = auth.create_access_token(uid=str(user.id))
    return LoginResponse(access_token=token)

@auth_router.get('/protected', dependencies=[Depends(auth.access_token_required)])
async def protected():
    return {'message': 'Hello World'}
