from functools import lru_cache
from typing import Optional

from fastapi_mail import (
    FastMail,
    ConnectionConfig,
    MessageSchema,
    MessageType,
    NameEmail,
)
from pydantic import SecretStr, TypeAdapter
from core.setting import get_settings

settings = get_settings()
_fast_mail: Optional[FastMail] = None
_recipients_adapter = TypeAdapter(list[NameEmail])


@lru_cache
def get_mail():
    global _fast_mail
    if _fast_mail is None:
        conf = ConnectionConfig(
            MAIL_USERNAME=settings.mail_username,
            MAIL_PASSWORD=SecretStr(settings.mail_password),
            MAIL_FROM=settings.mail_from,
            MAIL_PORT=settings.mail_port,
            MAIL_SERVER=settings.mail_server,
            MAIL_FROM_NAME=settings.mail_from_name,
            MAIL_STARTTLS=settings.mail_starttls,
            MAIL_SSL_TLS=settings.mail_ssl_tls,
            USE_CREDENTIALS=True,
            VALIDATE_CERTS=True,
        )
        _fast_mail = FastMail(conf)

    return _fast_mail


async def send_email(subject: str, recipients: list[str], body: str) -> None:
    message = MessageSchema(
        subject=subject,
        recipients=_recipients_adapter.validate_python(recipients),
        body=body,
        subtype=MessageType.html,
    )
    await get_mail().send_message(message)
