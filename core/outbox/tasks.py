import logging
from datetime import UTC, datetime, timedelta

from core.database import AsyncSessionLocal
from core.outbox.repository import OutboxRepository
from core.outbox.settings import get_outbox_settings

logger = logging.getLogger(__name__)


async def cleanup_outbox_task(ctx):
    logger.info("Starting background cleanup of dispatched outbox rows")
    retention = timedelta(days=get_outbox_settings().retention_days)
    async with AsyncSessionLocal() as db:
        deleted = await OutboxRepository(db).purge_dispatched(
            datetime.now(UTC) - retention
        )
    logger.info("Deleted %d dispatched outbox rows past retention", deleted)
    return {"status": "completed", "deleted": deleted}
