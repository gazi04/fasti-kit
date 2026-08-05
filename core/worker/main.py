import logging

from core.queue import task_queue

from .tasks import process_welcome_email

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | WORKER | %(levelname)s | %(message)s",
    force=True
)

settings = {
    "queue": task_queue,
    "functions": [process_welcome_email],
    "concurrency": 10,
}
