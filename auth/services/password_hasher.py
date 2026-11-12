import asyncio
import contextvars
import secrets
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from prometheus_client import Counter, Gauge

from core.exception import ServiceUnavailableError
from core.setting import get_settings

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
    settings = get_settings()
    return PasswordHasher(
        settings.password_hash_workers,
        settings.password_hash_queue_per_worker,
        settings.password_hash_retry_after,
    )


password_hasher = _build_password_hasher()
PENDING.set_function(lambda: password_hasher.pending)


async def close_password_hasher() -> None:
    password_hasher.shutdown()
