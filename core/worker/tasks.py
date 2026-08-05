import asyncio
import logging

logger = logging.getLogger(__name__)


async def process_welcome_email(ctx, user_id: int, email: str):
    print(f"\n🚀 WORKER PICKED UP JOB: Sending email to {email} (User {user_id})!\n")

    logger.info(f"Starting email job for {email} (User {user_id})")
    await asyncio.sleep(2)
    logger.info(f"Successfully sent email to {email}")

    return {"status": "delivered", "user_id": user_id}
