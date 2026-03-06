"""
AI Jobs API — Phase 2 endpoints for inspecting and managing AI processing jobs.

All endpoints are tenant-scoped via JWT.
"""
import uuid
from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DB, CurrentTenant, AgentOrOwner, OwnerOnly
from app.models.ai_job import AIJobStatus
from app.schemas.ai_job import AIJobResponse, AIJobRetryResponse
from app.schemas.ai_result import AIResultResponse
from app.schemas.common import PaginatedResponse
from app.services.ai_job_service import ai_job_service

router = APIRouter(prefix="/ai/jobs", tags=["AI Jobs"])


@router.get("", response_model=PaginatedResponse[AIJobResponse])
async def list_ai_jobs(
    db: DB,
    current_tenant: CurrentTenant,
    _: AgentOrOwner,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: AIJobStatus | None = Query(None, description="Filter by job status"),
    ticket_id: uuid.UUID | None = Query(None, description="Filter by ticket ID"),
):
    """
    List AI jobs for the current tenant.
    Useful for monitoring and debugging the AI processing pipeline.
    """
    jobs, total = await ai_job_service.get_all(
        db,
        tenant_id=current_tenant.id,
        status=status,
        ticket_id=ticket_id,
        skip=(page - 1) * page_size,
        limit=page_size,
    )
    return PaginatedResponse.create(
        items=[AIJobResponse.model_validate(j) for j in jobs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{job_id}", response_model=AIJobResponse)
async def get_ai_job(
    job_id: uuid.UUID,
    db: DB,
    current_tenant: CurrentTenant,
    _: AgentOrOwner,
):
    """Get the status and metadata of a specific AI job."""
    job = await ai_job_service.get_by_id(db, job_id, current_tenant.id)
    if not job:
        raise HTTPException(status_code=404, detail="AI job not found")
    return AIJobResponse.model_validate(job)


@router.get("/{job_id}/result", response_model=AIResultResponse)
async def get_ai_job_result(
    job_id: uuid.UUID,
    db: DB,
    current_tenant: CurrentTenant,
    _: AgentOrOwner,
):
    """
    Get the structured AI decision result for a completed job.
    Returns 404 if the job has not completed yet.
    """
    result = await ai_job_service.get_result_by_job(db, job_id, current_tenant.id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="AI result not available — job may not have completed yet",
        )
    return AIResultResponse.model_validate(result)


@router.post("/{job_id}/retry", response_model=AIJobRetryResponse)
async def retry_ai_job(
    job_id: uuid.UUID,
    db: DB,
    current_tenant: CurrentTenant,
    _: AgentOrOwner,
):
    """
    Retry a failed AI job.
    - Resets the job to 'pending' status.
    - Re-enqueues it for processing (best-effort).
    - Only allowed when status == 'failed'.
    """
    job = await ai_job_service.get_by_id(db, job_id, current_tenant.id)
    if not job:
        raise HTTPException(status_code=404, detail="AI job not found")
    if job.status != AIJobStatus.failed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot retry job in status '{job.status}'. Only 'failed' jobs can be retried.",
        )

    job = await ai_job_service.reset_for_retry(db, job)
    await db.commit()

    # Re-enqueue (best-effort)
    from app.core.queue import enqueue_ai_job
    await enqueue_ai_job(str(job.id))

    return AIJobRetryResponse(
        ai_job_id=job.id,
        message="Job reset to pending and re-enqueued for processing",
        new_status=job.status,
    )
