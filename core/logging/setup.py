import json
import logging
import logging.config
from datetime import UTC, datetime
from typing import Any

from core.middlewares.correlation import request_id_context
from core.setting import get_settings

_NON_EXTRA_FIELDS = frozenset(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "request_id",
    "color_message",
}


class RequestIdFilter(logging.Filter):
    """Injects the current request_id into the log record."""

    def filter(self, record):
        record.request_id = request_id_context.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            entry["stack"] = self.formatStack(record.stack_info)
        entry.update(
            (key, value)
            for key, value in vars(record).items()
            if key not in _NON_EXTRA_FIELDS
        )
        return json.dumps(entry, default=str)


def build_logging_config(json_logs: bool, echo_sql: bool = False) -> dict[str, Any]:
    console = {
        "level": "INFO",
        "class": "logging.StreamHandler",
        "stream": "ext://sys.stdout",
        "formatter": "json" if json_logs else "standard",
        "filters": ["request_id_filter"],
    }
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"request_id_filter": {"()": RequestIdFilter}},
        "formatters": {
            "standard": {
                "format": "%(asctime)s | %(levelname)-8s | "
                "[%(request_id)s] | %(name)s | %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {"()": JsonFormatter},
        },
        "handlers": {"console": console},
        "loggers": {
            "": {"handlers": ["console"], "level": "INFO"},
            **{
                name: {"handlers": ["console"], "level": "INFO", "propagate": False}
                for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
            },
            "sqlalchemy.engine": {"level": "INFO" if echo_sql else "WARNING"},
        },
    }


def setup_logging() -> None:
    settings = get_settings()
    logging.config.dictConfig(
        build_logging_config(
            json_logs=settings.environment == "production",
            echo_sql=settings.db_echo,
        )
    )
