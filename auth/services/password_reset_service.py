from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt

from core.queue import task_queue
from core.setting import get_settings

settings = get_settings()
RESET_TOKEN_EXPIRY = timedelta(minutes=15)
RESET_TYPE = "password_reset"


class PasswordResetService:
    @staticmethod
    def create_reset_token(user_id: str) -> tuple[str, str]:
        now = datetime.now(UTC)
        jti = uuid4().hex
        payload = {
            "sub": user_id,
            "type": RESET_TYPE,
            "jti": jti,
            "iat": now,
            "exp": now + RESET_TOKEN_EXPIRY,
        }

        return jwt.encode(
            payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
        ), jti

    @staticmethod
    async def send_reset_email(email: str, token: str) -> None:
        link = f"{settings.backend_url}/api/auth/reset-password?token={token}"
        body = f'<p>Click to reset your password: <a href="{link}">{link}</a></p>'
        await task_queue.enqueue(
            "send_email_task",
            subject="Reset your password",
            recipients=[email],
            body=body,
        )

    @staticmethod
    async def decode_reset_token(token: str) -> dict[str, Any]:
        return jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
