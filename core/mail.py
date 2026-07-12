from fastapi_mail import FastMail, ConnectionConfig, MessageSchema, MessageType
from core.setting import get_settings

settings = get_settings()

conf = ConnectionConfig(
    MAIL_USERNAME = settings.mail_username,
    MAIL_PASSWORD = settings.mail_password,
    MAIL_FROM = settings.mail_from,
    MAIL_PORT = settings.mail_port,
    MAIL_SERVER = settings.mail_server,
    MAIL_FROM_NAME = settings.mail_from_name,
    MAIL_STARTTLS = settings.mail_starttls,
    MAIL_SSL_TLS = settings.mail_ssl_tls,
    USE_CREDENTIALS = True,
    VALIDATE_CERTS = True
)

fast_mail = FastMail(conf)

async def send_email(subject: str, recipients: list[str], body: str) -> None:
    message = MessageSchema(subject=subject, recipients=recipients, body=body, subtype=MessageType.html)
    await fast_mail.send_message(message)
