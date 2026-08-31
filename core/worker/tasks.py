import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.dead_letter.repository import DeadLetterJobRepository
from core.mail import send_email
from core.outbox.relay import cleanup_dispatched
from core.setting import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def process_welcome_email(ctx, user_id: int, email: str):
    logger.info(f"Starting email job for {email} (User {user_id})")
    await asyncio.sleep(2)
    logger.info(f"Successfully sent email to {email}")

    return {"status": "delivered", "user_id": user_id}


async def send_email_task(ctx, subject: str, recipients: list[str], body: str):
    logger.info(
        f"Starting background email job for {recipients} with subject: '{subject}'"
    )
    await send_email(subject=subject, recipients=recipients, body=body)
    logger.info(f"Successfully sent background email to {recipients}")
    return {"status": "sent", "recipients": recipients}


async def cleanup_revoked_tokens_task(ctx):
    logger.info("Starting background cleanup of expired revoked tokens")
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM revoked_tokens WHERE expires_at <= NOW()"))
        await db.commit()
    logger.info("Successfully cleaned up expired tokens")
    return {"status": "completed"}


async def cleanup_outbox_task(ctx):
    logger.info("Starting background cleanup of dispatched outbox rows")
    async with AsyncSessionLocal() as db:
        deleted = await cleanup_dispatched(db)
    logger.info("Deleted %d dispatched outbox rows past retention", deleted)
    return {"status": "completed", "deleted": deleted}


async def cleanup_dead_letter_task(ctx):
    logger.info("Starting background cleanup of retried dead-letter rows")
    cutoff = datetime.now(UTC) - timedelta(days=settings.dead_letter_retention_days)
    async with AsyncSessionLocal() as db:
        deleted = await DeadLetterJobRepository(db).purge(
            before=cutoff, only_retried=True
        )
    logger.info("Deleted %d retried dead-letter rows past retention", deleted)
    return {"status": "completed", "deleted": deleted}
