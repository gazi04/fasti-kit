import asyncio
import contextvars
import json
import logging
import sys
from types import SimpleNamespace

from core.logging.setup import JsonFormatter, RequestIdFilter, build_logging_config
from core.middlewares.correlation import request_id_context
from core.worker.main import _bind_job_correlation_id
from core.worker.main import settings as worker_settings


def _record(**kwargs) -> logging.LogRecord:
    defaults = {
        "name": "fasti.test",
        "level": logging.INFO,
        "pathname": __file__,
        "lineno": 1,
        "msg": "hello %s",
        "args": ("world",),
        "exc_info": None,
    }
    record = logging.LogRecord(**{**defaults, **kwargs})
    RequestIdFilter().filter(record)
    return record


def _in_fresh_context(fn):
    return contextvars.copy_context().run(fn)


def test_json_formatter_writes_one_parseable_object_with_correlation_id() -> None:
    def run() -> dict:
        request_id_context.set("req-123")
        record = _record()
        record.user_id = 7
        return json.loads(JsonFormatter().format(record))

    entry = _in_fresh_context(run)

    assert entry["level"] == "INFO"
    assert entry["logger"] == "fasti.test"
    assert entry["message"] == "hello world"
    assert entry["correlation_id"] == "req-123"
    assert entry["user_id"] == 7
    assert entry["timestamp"].endswith("+00:00")
    assert "request_id" not in entry
    assert "exception" not in entry


def test_json_formatter_includes_the_traceback() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = _record(exc_info=sys.exc_info())

    entry = json.loads(JsonFormatter().format(record))

    assert "ValueError: boom" in entry["exception"]
    assert "Traceback" in entry["exception"]


def test_json_formatter_stringifies_values_json_cannot_encode() -> None:
    record = _record()
    record.payload = {1, 2}

    entry = json.loads(JsonFormatter().format(record))

    assert entry["payload"] == "{1, 2}"


def test_json_formatter_drops_uvicorns_ansi_colored_duplicate() -> None:
    record = _record()
    record.color_message = "hello \x1b[36m%s\x1b[0m"

    entry = json.loads(JsonFormatter().format(record))

    assert "color_message" not in entry


def test_logging_config_writes_only_to_stdout() -> None:
    for json_logs, formatter in ((True, "json"), (False, "standard")):
        config = build_logging_config(json_logs)

        assert list(config["handlers"]) == ["console"]
        console = config["handlers"]["console"]
        assert console["class"] == "logging.StreamHandler"
        assert console["stream"] == "ext://sys.stdout"
        assert console["formatter"] == formatter
        assert "filename" not in json.dumps(config, default=str)


def test_logging_config_routes_uvicorn_loggers_through_console_once() -> None:
    loggers = build_logging_config(json_logs=True)["loggers"]

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert loggers[name] == {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        }


async def test_sql_echo_goes_through_the_console_handler_only_when_enabled() -> None:
    assert build_logging_config(json_logs=True, echo_sql=True)["loggers"][
        "sqlalchemy.engine"
    ] == {"level": "INFO"}
    assert build_logging_config(json_logs=True)["loggers"]["sqlalchemy.engine"] == {
        "level": "WARNING"
    }


async def test_worker_binds_the_job_key_as_correlation_id() -> None:
    job = SimpleNamespace(key="outbox:42")

    async def run() -> str:
        await _bind_job_correlation_id({"job": job})
        return json.loads(JsonFormatter().format(_record()))["correlation_id"]

    request_id = await asyncio.create_task(run())

    assert request_id == "outbox:42"
    assert request_id_context.get() == "-"


def test_worker_registers_the_correlation_hook() -> None:
    assert worker_settings["before_process"] is _bind_job_correlation_id
