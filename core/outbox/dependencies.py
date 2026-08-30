from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.outbox.repository import OutboxRepository


def get_outbox_repository(db: AsyncSession = Depends(get_db)) -> OutboxRepository:
    return OutboxRepository(db)
