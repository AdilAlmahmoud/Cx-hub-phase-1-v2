"""
Service layer for AIJob and AIResult CRUD operations.

All methods are tenant-scoped for isolation.
"""
import uuid
from typing import Optional, Tuple, List
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ai_job import AIJob, AIJobStatus
from app.models.ai_result import AIResult
from app.core.logging import get_logger

logger = get_logger(__name__)


class AIJobService:

    # ── AIJob ──────────────────────────────────────────────────────────────────

    async def create_job(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        ticket_id: uuid.UUID,
        conversation_id: uuid.UUID,
        event_log_id: Optional[uuid.UUID] = None,
        max_retries: int = 3,
    ) -> AIJob:
        """Create and persist a new AIJob in 'pending' status."""
        job = AIJob(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            conversation_id=conversation_id,
            event_log_id=event_log_id,
            status=AIJobStatus.pending,
            retry_count=0,
            max_retries=max_retries,
            scheduled_at=datetime.now(timezone.utc),
        )
        db.add(job)
        await db.flush()  # Assign ID without committing (caller commits)

        logger.info(
            "ai_job_created",
            ai_job_id=str(job.id),
            tenant_id=str(tenant_id),
            ticket_id=str(ticket_id),
        )
        return job

    async def get_by_id(
        self,
        db: AsyncSession,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Optional[AIJob]:
        """Load an AIJob by ID, scoped to tenant."""
        result = await db.execute(
            select(AIJob)
            .where(AIJob.id == job_id, AIJob.tenant_id == tenant_id)
            .options(selectinload(AIJob.ai_result))
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        status: Optional[AIJobStatus] = None,
        ticket_id: Optional[uuid.UUID] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[List[AIJob], int]:
        """List AI jobs for a tenant, optionally filtered by status or ticket."""
        q = select(AIJob).where(AIJob.tenant_id == tenant_id)
        if status is not None:
            q = q.where(AIJob.status == status)
        if ticket_id is not None:
            q = q.where(AIJob.ticket_id == ticket_id)

        count_result = await db.execute(
            select(func.count()).select_from(q.subquery())
        )
        total = count_result.scalar_one()

        q = q.order_by(AIJob.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(q)
        return list(result.scalars().all()), total

    async def reset_for_retry(
        self,
        db: AsyncSession,
        job: AIJob,
    ) -> AIJob:
        """
        Reset a failed job so it can be requeued.
        Only allowed when status == 'failed'.
        """
        job.status = AIJobStatus.pending
        job.error_message = None
        job.started_at = None
        job.completed_at = None
        job.scheduled_at = datetime.now(timezone.utc)
        await db.flush()

        logger.info(
            "ai_job_reset_for_retry",
            ai_job_id=str(job.id),
            retry_count=job.retry_count,
        )
        return job

    # ── AIResult ──────────────────────────────────────────────────────────────

    async def get_result_by_ticket(
        self,
        db: AsyncSession,
        ticket_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Optional[AIResult]:
        """
        Return the most recent AIResult for a ticket, scoped to tenant.
        (There is at most one result per job, and one job per inbound message.)
        """
        result = await db.execute(
            select(AIResult)
            .where(
                AIResult.ticket_id == ticket_id,
                AIResult.tenant_id == tenant_id,
            )
            .order_by(AIResult.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_result_by_job(
        self,
        db: AsyncSession,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Optional[AIResult]:
        """Return the AIResult for a specific job."""
        result = await db.execute(
            select(AIResult).where(
                AIResult.ai_job_id == job_id,
                AIResult.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()


ai_job_service = AIJobService()
