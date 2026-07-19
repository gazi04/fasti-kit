from sqlalchemy import text
from core.database import engine
from core.setting import get_settings

settings = get_settings()

class StartupCheckError(RuntimeError):
    pass

async def check_database() -> None:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        raise StartupCheckError(
                f"Cannot reach Postgres at {settings.database_url!r}"
                f"Is it running? Try: docker comp up -d"
                )

async def check_mail_config() -> None:
    required = {
            "MAIL_USERNAME": settings.mail_username,
            "MAIL_PASSWORD": settings.mail_password,
            "MAIL_FROM": settings.mail_from,
            "MAIL_PORT": settings.mail_port,
            "MAIL_SERVER": settings.mail_server,
            }

    missing = [key for key, value in required.items() if value is None]
    if missing:
        raise StartupCheckError(
                f"Missing SMTP configuration: {', '.join(missing)}. "
                f"Set these in .env — see .env.example."
                )

async def check_jwt_config() -> None:
    required = {
            "JWT_SECRET_KEY": settings.jwt_secret_key,
            "JWT_ALGORITHM": settings.jwt_algorithm,
            }

    missing = [key for key, value in required.items() if not value]
    if missing:
        raise StartupCheckError(
                f"Missing JWT configuration: {', '.join(missing)}. "
                f"Set these in .env — see .env.example."
                )

