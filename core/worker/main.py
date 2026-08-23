import logging

from saq import CronJob

from core.queue import task_queue

from .tasks import cleanup_revoked_tokens_task, process_welcome_email, send_email_task

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | WORKER | %(levelname)s | %(message)s",
    force=True,
)

settings = {
    "queue": task_queue,
    "functions": [process_welcome_email, send_email_task],
    "cron_jobs": [CronJob(cleanup_revoked_tokens_task, cron="0 3 * * *")],
    "concurrency": 10,
}
