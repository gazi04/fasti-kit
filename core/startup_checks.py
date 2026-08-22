import logging

from sqlalchemy import text

from core.database import primary_engine, replica_engine
from core.setting import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class StartupCheckError(RuntimeError):
    pass


async def check_database() -> None:
    try:
        async with primary_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as err:
        raise StartupCheckError(
            f"Cannot reach Primary Postgres at {settings.database_url!r}. "
            f"Is it running? Try: docker compose up -d"
        ) from err

    try:
        async with replica_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.warning(
            f"Replica Postgres at {settings.get_replica_url!r} is not reachable. "
            f"Read traffic will route to primary until it is available."
        )


async def check_mail_config() -> None:
    required = {
        "MAIL_FROM": settings.mail_from,
        "MAIL_PORT": settings.mail_port,
        "MAIL_SERVER": settings.mail_server,
    }

    missing = [key for key, value in required.items() if not value]
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
