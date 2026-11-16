import asyncio
import contextvars
import math
import os
import secrets
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from prometheus_client import Counter, Gauge
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.exception import ServiceUnavailableError

CGROUP_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")


def cgroup_cpu_limit(cpu_max: Path = CGROUP_CPU_MAX) -> int | None:
    try:
        quota, period = cpu_max.read_text().split()
        return max(1, math.ceil(int(quota) / int(period)))
    except (OSError, ValueError):
        return None


def available_cpus() -> int:
    visible = os.process_cpu_count() or 1
    return min(visible, cgroup_cpu_limit() or visible)


def _default_workers() -> int:
    return max(1, available_cpus() - 1)


class PasswordHashSettings(BaseSettings):
    workers: int = Field(default_factory=_default_workers, ge=1)
    queue_per_worker: int = Field(default=4, ge=1)
    retry_after: int = Field(default=1, ge=1)

    model_config = SettingsConfigDict(
        env_prefix="PASSWORD_HASH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


REJECTED = Counter(
    "password_hash_rejected_total",
    "Password hashes refused because the hasher had no room left.",
)
PENDING = Gauge(
    "password_hash_pending",
    "Password hashes running or waiting for a worker thread.",
)


class PasswordHasher:
    def __init__(self, workers: int, queue_per_worker: int, retry_after: int) -> None:
        self.workers = workers
        self.max_pending = workers * queue_per_worker
        self.retry_after = retry_after
        self._pending = 0
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None

    @property
    def pending(self) -> int:
        return self._pending

    async def run[**P, T](
        self, function: Callable[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        self._reserve_slot()
        context = contextvars.copy_context()
        try:
            future = self._get_executor().submit(context.run, function, *args, **kwargs)
        except BaseException:
            self._release_slot()
            raise
        future.add_done_callback(self._release_slot_when_done)
        return await asyncio.wrap_future(future)

    def shutdown(self) -> None:
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def _reserve_slot(self) -> None:
        with self._lock:
            if self._pending >= self.max_pending:
                REJECTED.inc()
                raise ServiceUnavailableError(
                    "Too many password operations are running. Try again shortly.",
                    self.retry_after + secrets.randbelow(self.retry_after + 1),
                )
            self._pending += 1

    def _release_slot(self) -> None:
        with self._lock:
            self._pending -= 1

    def _release_slot_when_done(self, _future: Future) -> None:
        self._release_slot()

    def _get_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self.workers, thread_name_prefix="bcrypt"
                )
            return self._executor


def _build_password_hasher() -> PasswordHasher:
    settings = PasswordHashSettings()
    return PasswordHasher(
        settings.workers, settings.queue_per_worker, settings.retry_after
    )


password_hasher = _build_password_hasher()
PENDING.set_function(lambda: password_hasher.pending)


async def close_password_hasher() -> None:
    password_hasher.shutdown()
