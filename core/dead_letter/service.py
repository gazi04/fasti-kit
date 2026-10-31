from datetime import datetime
from uuid import UUID

from fastapi_pagination.cursor import CursorPage, CursorParams

from core.dead_letter.entity import DeadLetterJob
from core.dead_letter.repository import DeadLetterJobRepository
from core.exception import BadRequestError, ConflictError, EntityNotFoundError

ENTITY_NAME = "Dead-letter job"


class DeadLetterJobService:
    def __init__(self, repo: DeadLetterJobRepository) -> None:
        self.repo = repo

    async def list_jobs(
        self, params: CursorParams, *, unresolved_only: bool = False
    ) -> CursorPage[DeadLetterJob]:
        return await self.repo.list(params, unresolved_only=unresolved_only)

    async def get_job(self, job_id: UUID) -> DeadLetterJob:
        row = await self.repo.get(job_id)

        if row is None:
            raise EntityNotFoundError(ENTITY_NAME, str(job_id))

        return row

    async def delete_job(self, job_id: UUID) -> None:
        if not await self.repo.delete(job_id):
            raise EntityNotFoundError(ENTITY_NAME, str(job_id))

    async def retry_job(self, job_id: UUID) -> DeadLetterJob:
        retried = await self.repo.retry(job_id)

        if retried is not None:
            return retried

        if await self.repo.get(job_id, consistent=True) is None:
            raise EntityNotFoundError(ENTITY_NAME, str(job_id))

        raise ConflictError("job already retried")

    async def purge(
        self, *, before: datetime | None = None, only_retried: bool = True
    ) -> int:
        if before is None and not only_retried:
            raise BadRequestError(
                "Specify 'before' or keep 'only_retried' true to bound the purge"
            )

        return await self.repo.purge(before=before, only_retried=only_retried)
