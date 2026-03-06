"""
ARQ worker tasks for Phase 2 AI processing.

Design rules:
- Every task is idempotent: re-running with the same job ID is safe.
- Core logic lives in _process_ai_job_inner() so tests can call it directly
  without a running Redis instance.
- Failures increment retry_count; when max_retries is exceeded the job is
  marked 'failed' permanently.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProcessingContext, ConversationMessage
from app.ai.engine import AIDecisionEngine, get_ai_provider
from app.core.logging import get_logger
from app.models.ai_job import AIJob, AIJobStatus
from app.models.ai_result import AIResult
from app.models.event_log import EventLog
from app.models.tenant import TenantConfig

logger = get_logger(__name__)


# ── Internal processing logic (testable without ARQ/Redis) ────────────────────

async def _process_ai_job_inner(db: AsyncSession, ai_job_id: str) -> dict:
    """
    Core processing logic for a single AI job.

    Idempotency guarantee:
    - If status is already 'completed' → skip (return early).
    - If status is 'failed' and retry_count >= max_retries → skip.
    - Otherwise process regardless of current status (handles requeued jobs).
    """
    job_uuid = uuid.UUID(ai_job_id)

    # ── 1. Load job ───────────────────────────────────────────────────────────
    result = await db.execute(select(AIJob).where(AIJob.id == job_uuid))
    job: Optional[AIJob] = result.scalar_one_or_none()

    if job is None:
        logger.error("ai_job_not_found", ai_job_id=ai_job_id)
        return {"status": "not_found", "ai_job_id": ai_job_id}

    # ── 2. Idempotency check ──────────────────────────────────────────────────
    if job.status == AIJobStatus.completed:
        logger.info("ai_job_already_completed", ai_job_id=ai_job_id)
        return {"status": "skipped", "reason": "already_completed", "ai_job_id": ai_job_id}

    if job.status == AIJobStatus.failed and job.retry_count >= job.max_retries:
        logger.info("ai_job_max_retries_exceeded", ai_job_id=ai_job_id)
        return {"status": "skipped", "reason": "max_retries_exceeded", "ai_job_id": ai_job_id}

    # ── 3. Mark as processing ─────────────────────────────────────────────────
    job.status = AIJobStatus.processing
    job.started_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(
        "ai_job_processing_start",
        ai_job_id=ai_job_id,
        tenant_id=str(job.tenant_id),
        ticket_id=str(job.ticket_id),
        retry_count=job.retry_count,
    )

    try:
        # ── 4. Load tenant AI config ──────────────────────────────────────────
        cfg_result = await db.execute(
            select(TenantConfig).where(TenantConfig.tenant_id == job.tenant_id)
        )
        tenant_cfg: Optional[TenantConfig] = cfg_result.scalar_one_or_none()

        ai_language = getattr(tenant_cfg, "ai_language", "en") if tenant_cfg else "en"
        ai_tone = getattr(tenant_cfg, "ai_tone", "professional") if tenant_cfg else "professional"
        confidence_threshold = getattr(tenant_cfg, "confidence_threshold", 0.7) if tenant_cfg else 0.7
        auto_send_mode = getattr(tenant_cfg, "auto_send_mode", "off") if tenant_cfg else "off"
        escalation_keywords = getattr(tenant_cfg, "escalation_keywords", None) if tenant_cfg else None
        handoff_template = getattr(tenant_cfg, "handoff_message_template", None) if tenant_cfg else None

        # ── 5. Load conversation history (last 10 events) ─────────────────────
        events_result = await db.execute(
            select(EventLog)
            .where(EventLog.conversation_id == job.conversation_id)
            .order_by(EventLog.event_timestamp.asc())
            .limit(10)
        )
        event_rows = events_result.scalars().all()
        history = [
            ConversationMessage(
                direction=row.direction,
                message_text=row.message_text,
                timestamp=row.event_timestamp,
                channel=row.channel,
            )
            for row in event_rows
        ]

        # Derive message_text from the triggering event_log
        message_text: Optional[str] = None
        if job.event_log_id:
            for evt in event_rows:
                if evt.id == job.event_log_id:
                    message_text = evt.message_text
                    channel = evt.channel
                    break
            else:
                # Fallback: use the last inbound message in history
                inbound = [e for e in event_rows if e.direction == "inbound"]
                message_text = inbound[-1].message_text if inbound else None
                channel = inbound[-1].channel if inbound else "unknown"
        else:
            inbound = [e for e in event_rows if e.direction == "inbound"]
            message_text = inbound[-1].message_text if inbound else None
            channel = inbound[-1].channel if inbound else "unknown"

        # ── 6. Build context and run AI engine ────────────────────────────────
        context = AIProcessingContext(
            ai_job_id=ai_job_id,
            tenant_id=str(job.tenant_id),
            ticket_id=str(job.ticket_id),
            conversation_id=str(job.conversation_id),
            message_text=message_text,
            channel=channel,
            conversation_history=history,
            ai_language=ai_language,
            ai_tone=ai_tone,
            confidence_threshold=confidence_threshold,
            auto_send_mode=auto_send_mode,
            escalation_keywords=escalation_keywords or [],
            handoff_message_template=handoff_template,
        )

        provider = get_ai_provider()
        engine = AIDecisionEngine(provider=provider)
        decision = await engine.process(context)

        # ── 7. Persist AIResult ───────────────────────────────────────────────
        ai_result = AIResult(
            tenant_id=job.tenant_id,
            ai_job_id=job.id,
            ticket_id=job.ticket_id,
            intent=decision.intent,
            answer=decision.answer,
            confidence=decision.confidence,
            should_escalate=decision.should_escalate,
            risk_flags=decision.risk_flags or [],
            escalation_reason=decision.escalation_reason,
            safe_to_auto_send=decision.safe_to_auto_send,
            processing_notes=decision.processing_notes,
            provider_name=decision.provider_name,
            model_name=decision.model_name,
            processing_duration_ms=decision.processing_duration_ms,
            raw_provider_response=None,  # Populated by real providers in Phase 3
        )
        db.add(ai_result)

        # ── 8. Mark job completed ─────────────────────────────────────────────
        job.status = AIJobStatus.completed
        job.completed_at = datetime.now(timezone.utc)
        await db.commit()

        logger.info(
            "ai_job_completed",
            ai_job_id=ai_job_id,
            intent=decision.intent,
            confidence=decision.confidence,
            should_escalate=decision.should_escalate,
            safe_to_auto_send=decision.safe_to_auto_send,
        )

        return {
            "status": "completed",
            "ai_job_id": ai_job_id,
            "intent": decision.intent,
            "should_escalate": decision.should_escalate,
            "safe_to_auto_send": decision.safe_to_auto_send,
        }

    except Exception as exc:
        # ── 9. Handle failure with retry tracking ─────────────────────────────
        job.retry_count += 1
        job.error_message = str(exc)[:2000]  # cap at 2k chars

        if job.retry_count >= job.max_retries:
            job.status = AIJobStatus.failed
            logger.error(
                "ai_job_failed_permanently",
                ai_job_id=ai_job_id,
                retry_count=job.retry_count,
                error=str(exc),
            )
        else:
            # Back to pending so it can be retried
            job.status = AIJobStatus.pending
            logger.warning(
                "ai_job_failed_will_retry",
                ai_job_id=ai_job_id,
                retry_count=job.retry_count,
                max_retries=job.max_retries,
                error=str(exc),
            )

        await db.commit()
        return {
            "status": job.status.value,
            "ai_job_id": ai_job_id,
            "error": str(exc),
            "retry_count": job.retry_count,
        }


# ── ARQ task entry point ───────────────────────────────────────────────────────

async def process_ai_job(ctx: dict, ai_job_id: str) -> dict:
    """
    ARQ task: process a single AI job.

    ctx must contain 'db_session_factory' (set in WorkerSettings.on_startup).
    This wrapper creates a fresh DB session per job and delegates to
    _process_ai_job_inner for testability.
    """
    db_factory = ctx.get("db_session_factory")
    if db_factory is None:
        logger.error("worker_missing_db_factory", ai_job_id=ai_job_id)
        return {"status": "error", "reason": "no_db_factory"}

    async with db_factory() as db:
        return await _process_ai_job_inner(db, ai_job_id)
