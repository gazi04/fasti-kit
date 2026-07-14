from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from core.mail import send_email
from core.setting import get_settings

import jwt

settings = get_settings()
VERIFY_TOKEN_EXPIRY = timedelta(hours=24)
VERIFY_TYPE = "email_verify"

class EmailVerficationService:
    @staticmethod
    def create_verification_token(user_id: str) -> tuple[str, str]:
        now = datetime.now(timezone.utc)
        jti = uuid4().hex
        payload = {
                "sub": user_id,
                "type": VERIFY_TYPE,
                "jti": jti,
                "iat": now,
                "exp": now + VERIFY_TOKEN_EXPIRY,
                }

        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm), jti

    @staticmethod
    async def send_verification_email(email: str, token: str) -> None:
        link = f"{settings.backend_url}/api/auth/verify-email?token={token}"
        body = f'<p>Click to verify your account: <a href="{link}">{link}</a></p>'
        await send_email(subject="Verify your email", recipients=[email], body=body)

    @staticmethod
    def decode_verification_token(token: str) -> dict[str, Any]:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
