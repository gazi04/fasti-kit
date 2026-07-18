from authx import JWTDecodeError, TokenPayload
from fastapi import Request

from auth.dependencies import auth
from auth.repositories.revoked_token_repository import RevokedTokenRepository
from core.setting import get_settings

settings = get_settings()


class TokenService:
    @staticmethod
    async def revoke_tokens(request: Request, payload: TokenPayload, db):
        repo = RevokedTokenRepository(db)
        if payload.jti is not None:
            try:
                await repo.add(payload.jti, payload.expiry_datetime)
            except ValueError:
                pass

        refresh_token = request.cookies.get(auth.config.JWT_REFRESH_COOKIE_NAME)
        if refresh_token:
            try:
                refresh_payload = TokenPayload.decode(
                    refresh_token,
                    key=settings.jwt_secret_key,
                    algorithms=[settings.jwt_algorithm],
                    verify=False,
                )
                if refresh_payload.jti is not None:
                    await repo.add(refresh_payload.jti, refresh_payload.expiry_datetime)
            except JWTDecodeError:
                pass
