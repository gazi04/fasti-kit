from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.dead_letter.repository import DeadLetterJobRepository
from core.dead_letter.service import DeadLetterJobService


def get_dead_letter_repository(
    db: AsyncSession = Depends(get_db),
) -> DeadLetterJobRepository:
    return DeadLetterJobRepository(db)


def get_dead_letter_service(
    repo: DeadLetterJobRepository = Depends(get_dead_letter_repository),
) -> DeadLetterJobService:
    return DeadLetterJobService(repo)
