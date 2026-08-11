import logging

from sqlalchemy.engine import make_url

from core.setting import get_settings

logger = logging.getLogger(__name__)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


class SafetyError(RuntimeError):
    """Raised when a command would run a destructive/dev-only operation in production."""


def ensure_safe_operation(
    operation: str,
    *,
    allow_production: bool = False,
    environment: str | None = None,
    database_url: str | None = None,
) -> None:
    """Refuse to run `operation` in production unless `allow_production` is set.

    Reads settings at call time (not import time) and accepts overrides so
    tests can exercise both branches without touching the real .env.
    """
    settings = get_settings()
    env = environment or settings.environment
    url = database_url or settings.database_url

    if env == "production" and not allow_production:
        raise SafetyError(
            f"Refusing to run '{operation}' in the {env} environment. "
            "This command can destroy data. Re-run with --allow-production "
            "only if you are certain."
        )

    host = make_url(url).host or ""
    if env != "production" and host not in LOCAL_HOSTS:
        logger.warning(
            "'%s' is about to run against a non-local database host %r "
            "(environment=%s). Double-check this DATABASE_URL before continuing.",
            operation,
            host,
            env,
        )
