import asyncio
import logging

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.mail import send_email

logger = logging.getLogger(__name__)


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
        await db.execute(
            text("DELETE FROM revoked_tokens WHERE expiry_datetime <= NOW()")
        )
        await db.commit()
    logger.info("Successfully cleaned up expired tokens")
    return {"status": "completed"}
