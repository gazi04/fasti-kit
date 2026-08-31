"""SAQ ``after_process`` hook that records terminally-failed jobs.

``after_process`` runs once per attempt in ``Worker.process``'s ``finally``,
after ``job.finish()`` / ``job.retry()`` has already run — so ``job.status`` is
``FAILED``/``ABORTED`` only on the terminal, non-retryable attempt (``QUEUED``
when the job will retry, ``COMPLETE`` on success).

Not captured: jobs re-queued or aborted by SAQ's ``sweep`` (a job stuck past the
sweep timeout, or the worker hard-killed mid-job) go through ``Worker.upkeep``,
not ``Worker.process``, so this hook never sees them.
"""

import logging

from saq.job import Job, Status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from core.dead_letter.entity import DeadLetterJob
from core.dead_letter.repository import DeadLetterJobRepository

logger = logging.getLogger(__name__)

_DEAD_LETTER_STATUSES = frozenset({Status.FAILED, Status.ABORTED})


async def record_dead_letter_job(db: AsyncSession, job: Job) -> DeadLetterJob:
    return await DeadLetterJobRepository(db).record(
        job_key=job.key,
        function=job.function,
        queue_name=job.queue.name if job.queue else "default",
        kwargs=dict(job.kwargs or {}),
        status=job.status.value,
        error=job.error,
        attempts=job.attempts,
    )


async def record_dead_letter(ctx) -> None:
    job = ctx.get("job")
    if job is None or job.status not in _DEAD_LETTER_STATUSES:
        return

    try:
        async with AsyncSessionLocal() as db:
            await record_dead_letter_job(db, job)
    except Exception:
        logger.exception(
            "Failed to record dead-letter job %s", getattr(job, "key", "?")
        )
