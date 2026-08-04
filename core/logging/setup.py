import logging
import logging.config
import os

from core.middlewares.correlation import request_id_context


class RequestIdFilter(logging.Filter):
    """Injects the current request_id into the log record."""

    def filter(self, record):
        record.request_id = request_id_context.get()
        return True


def setup_logging():
    # Ensure the logs directory exists so FileHandler doesn't crash
    os.makedirs("logs", exist_ok=True)

    logging.config.dictConfig(
        {
            "version": 1,
            # CRITICAL: Set to False so Uvicorn's loggers are untouched
            "disable_existing_loggers": False,
            "filters": {
                "request_id_filter": {
                    "()": RequestIdFilter,
                }
            },
            "formatters": {
                "standard": {
                    "format": "%(asctime)s | %(levelname)-8s | "
                    "[%(request_id)s] | %(name)s | %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                },
            },
            "handlers": {
                # Handler 1: Terminal output
                "console": {
                    "level": "INFO",
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "filters": ["request_id_filter"],
                },
                # Handler 2: File output
                "file": {
                    "level": "INFO",
                    "class": "logging.FileHandler",
                    "filename": "logs/app.log",
                    "formatter": "standard",
                    "filters": ["request_id_filter"],
                },
            },
            "loggers": {
                # Route our root application logs to both file and console
                "": {
                    "handlers": ["console", "file"],
                    "level": "INFO",
                },
            },
        }
    )
