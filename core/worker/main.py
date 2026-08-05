from core.queue import task_queue
from .tasks import process_welcome_email

# SAQ looks for a dictionary named 'settings' by default
settings = {
    "queue": task_queue,
    "functions": [process_welcome_email],
    "concurrency": 10, # Number of jobs to process concurrently
}
