from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_pagination.cursor import CursorPage, CursorParams

from auth.dependencies import require_scopes
from core.dead_letter.dependencies import get_dead_letter_service
from core.dead_letter.entity import DeadLetterJob
from core.dead_letter.schema import DeadLetterJobResponse, PurgeRequest
from core.dead_letter.service import DeadLetterJobService

dlq_router = APIRouter(
    prefix="/api/admin/tasks/dlq",
    tags=["Dead Letter Queue"],
    dependencies=[Depends(require_scopes("admin:read"))],
)


@dlq_router.get("", response_model=CursorPage[DeadLetterJobResponse])
async def list_dead_letter_jobs(
    params: CursorParams = Depends(),
    unresolved_only: bool = False,
    service: DeadLetterJobService = Depends(get_dead_letter_service),
) -> CursorPage[DeadLetterJob]:
    return await service.list_jobs(params, unresolved_only=unresolved_only)


@dlq_router.get("/{job_id}", response_model=DeadLetterJobResponse)
async def get_dead_letter_job(
    job_id: UUID,
    service: DeadLetterJobService = Depends(get_dead_letter_service),
) -> DeadLetterJob:
    job = await service.get_job(job_id)

    if job is None:
        raise HTTPException(404, "Dead-letter job not found")

    return job


@dlq_router.post("/{job_id}/retry")
async def retry_dead_letter_job(
    job_id: UUID,
    service: DeadLetterJobService = Depends(get_dead_letter_service),
):
    try:
        job = await service.retry_job(job_id)
    except ValueError as err:
        raise HTTPException(409, str(err)) from err

    if job is None:
        raise HTTPException(404, "Dead-letter job not found")

    return {"message": "re-enqueued", "job_key": job.job_key}


@dlq_router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dead_letter_job(
    job_id: UUID,
    service: DeadLetterJobService = Depends(get_dead_letter_service),
) -> None:
    deleted = await service.delete_job(job_id)

    if not deleted:
        raise HTTPException(404, "Dead-letter job not found")


@dlq_router.post("/purge")
async def purge_dead_letter_jobs(
    data: PurgeRequest,
    service: DeadLetterJobService = Depends(get_dead_letter_service),
):
    if data.before is None and not data.only_retried:
        raise HTTPException(
            400, "Specify 'before' or keep 'only_retried' true to bound the purge"
        )

    deleted = await service.purge(before=data.before, only_retried=data.only_retried)
    return {"deleted": deleted}
