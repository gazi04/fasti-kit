import logging
from datetime import UTC, datetime, timedelta

from core.database import AsyncSessionLocal
from core.dead_letter.repository import DeadLetterJobRepository
from core.dead_letter.settings import get_dead_letter_settings

logger = logging.getLogger(__name__)


async def cleanup_dead_letter_task(ctx):
    logger.info("Starting background cleanup of retried dead-letter rows")
    retention = timedelta(days=get_dead_letter_settings().retention_days)
    async with AsyncSessionLocal() as db:
        deleted = await DeadLetterJobRepository(db).purge(
            before=datetime.now(UTC) - retention, only_retried=True
        )
    logger.info("Deleted %d retried dead-letter rows past retention", deleted)
    return {"status": "completed", "deleted": deleted}
