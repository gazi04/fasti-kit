from authx import JWTDecodeError, TokenPayload
from fastapi import Request

from auth.dependencies import auth
from auth.repositories.revoked_token_repository import RevokedTokenRepository


class TokenService:
    @staticmethod
    async def revoke_tokens(request: Request, payload: TokenPayload, db):
        repo = RevokedTokenRepository(db)
        try:
            await repo.add(payload.jti, payload.expiry_datetime)
        except ValueError:
            pass

        refresh_token = request.cookies.get(auth.config.JWT_REFRESH_COOKIE_NAME)
        if refresh_token:
            try:
                refresh_payload = TokenPayload.decode(
                    refresh_token,
                    key=auth.config.JWT_SECRET_KEY,
                    algorithms=[auth.config.JWT_ALGORITHM],
                    verify=False,
                )
                await repo.add(refresh_payload.jti, refresh_payload.expiry_datetime)
            except JWTDecodeError:
                pass
