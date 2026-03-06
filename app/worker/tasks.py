"""
ARQ worker tasks — Phase 2 AI processing + Phase 3 knowledge ingestion
                    + Phase 4 outbound delivery.

Design rules:
- Every task is idempotent: re-running with the same ID is safe.
- Core logic lives in _*_inner() functions so tests can call them directly
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


# ── AI Job (Phase 2 + Phase 3 RAG + Phase 4 auto-send) ───────────────────────

async def _process_ai_job_inner(db: AsyncSession, ai_job_id: str) -> dict:
    """
    Core processing logic for a single AI job.

    Idempotency guarantee:
    - If status is already 'completed' → skip (return early).
    - If status is 'failed' and retry_count >= max_retries → skip.
    - Otherwise process regardless of current status (handles requeued jobs).

    Phase 3: If knowledge_enabled=True, embeds the message and retrieves
    relevant knowledge chunks (RAG) before calling the AI engine.

    Phase 4: If outbound_enabled=True and safe_to_auto_send=True, creates
    and enqueues an OutboundMessage for delivery (non-fatal if it fails).
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
        knowledge_enabled = getattr(tenant_cfg, "knowledge_enabled", False) if tenant_cfg else False
        retrieval_top_k = getattr(tenant_cfg, "retrieval_top_k", 3) if tenant_cfg else 3
        outbound_enabled = getattr(tenant_cfg, "outbound_enabled", False) if tenant_cfg else False

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
        channel = "unknown"
        if job.event_log_id:
            for evt in event_rows:
                if evt.id == job.event_log_id:
                    message_text = evt.message_text
                    channel = evt.channel
                    break
            else:
                inbound = [e for e in event_rows if e.direction == "inbound"]
                message_text = inbound[-1].message_text if inbound else None
                channel = inbound[-1].channel if inbound else "unknown"
        else:
            inbound = [e for e in event_rows if e.direction == "inbound"]
            message_text = inbound[-1].message_text if inbound else None
            channel = inbound[-1].channel if inbound else "unknown"

        # ── 6. Phase 3: RAG retrieval (optional) ──────────────────────────────
        retrieved_chunks = []
        if knowledge_enabled and message_text:
            try:
                from app.embeddings.openai_provider import get_embedding_provider
                from app.services.knowledge_service import retrieve_similar_chunks

                embed_provider = get_embedding_provider()
                query_embedding = await embed_provider.embed_text(message_text)
                retrieved_chunks = await retrieve_similar_chunks(
                    db=db,
                    tenant_id=job.tenant_id,
                    query_embedding=query_embedding,
                    top_k=retrieval_top_k,
                )
                if retrieved_chunks:
                    logger.info(
                        "ai_rag_context_used",
                        ai_job_id=ai_job_id,
                        tenant_id=str(job.tenant_id),
                        chunk_count=len(retrieved_chunks),
                    )
            except Exception as rag_exc:
                # Non-fatal: continue without RAG context
                logger.warning(
                    "ai_rag_retrieval_failed",
                    ai_job_id=ai_job_id,
                    error=str(rag_exc),
                )

        # ── 7. Build context and run AI engine ────────────────────────────────
        from app.ai.base import RetrievedChunk as _RC
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
            retrieved_chunks=[
                _RC(
                    chunk_id=c.chunk_id,
                    knowledge_file_id=c.knowledge_file_id,
                    content=c.content,
                    chunk_index=c.chunk_index,
                    similarity_score=c.similarity_score,
                )
                for c in retrieved_chunks
            ],
        )

        provider = get_ai_provider()
        engine = AIDecisionEngine(provider=provider)
        decision = await engine.process(context)

        # ── 8. Persist AIResult ───────────────────────────────────────────────
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
            raw_provider_response=None,
            retrieved_chunk_ids=decision.retrieved_chunk_ids or [],
        )
        db.add(ai_result)

        # ── 9. Mark job completed ─────────────────────────────────────────────
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

        # ── 10. Phase 4: Auto-send if policy permits ──────────────────────────
        if outbound_enabled and decision.safe_to_auto_send and decision.answer:
            try:
                from app.models.conversation import Conversation
                from app.models.customer import Customer
                from app.services.outbound_service import create_outbound_message
                from app.core.queue import enqueue_outbound_message

                conv_r = await db.execute(
                    select(Conversation).where(Conversation.id == job.conversation_id)
                )
                conversation = conv_r.scalar_one_or_none()
                if conversation:
                    cust_r = await db.execute(
                        select(Customer).where(Customer.id == conversation.customer_id)
                    )
                    customer = cust_r.scalar_one_or_none()
                    if customer:
                        # Fetch persisted AIResult ID
                        ar_row = await db.execute(
                            select(AIResult).where(AIResult.ai_job_id == job.id)
                        )
                        persisted_result = ar_row.scalar_one_or_none()
                        outbound_msg = await create_outbound_message(
                            db=db,
                            tenant_id=job.tenant_id,
                            conversation_id=conversation.id,
                            channel=conversation.channel,
                            recipient_identifier=customer.external_id,
                            message_text=decision.answer,
                            ticket_id=job.ticket_id,
                            ai_result_id=persisted_result.id if persisted_result else None,
                            is_ai_generated=True,
                        )
                        await enqueue_outbound_message(str(outbound_msg.id))
                        logger.info(
                            "ai_auto_send_enqueued",
                            ai_job_id=ai_job_id,
                            outbound_message_id=str(outbound_msg.id),
                            channel=conversation.channel,
                        )
            except Exception as auto_send_exc:
                # Non-fatal: AI job is already completed, log and continue
                logger.warning(
                    "ai_auto_send_failed",
                    ai_job_id=ai_job_id,
                    error=str(auto_send_exc),
                )

        return {
            "status": "completed",
            "ai_job_id": ai_job_id,
            "intent": decision.intent,
            "should_escalate": decision.should_escalate,
            "safe_to_auto_send": decision.safe_to_auto_send,
        }

    except Exception as exc:
        # ── 11. Handle failure with retry tracking ────────────────────────────
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


async def process_ai_job(ctx: dict, ai_job_id: str) -> dict:
    """
    ARQ task: process a single AI job.

    ctx must contain 'db_session_factory' (set in WorkerSettings.on_startup).
    """
    db_factory = ctx.get("db_session_factory")
    if db_factory is None:
        logger.error("worker_missing_db_factory", ai_job_id=ai_job_id)
        return {"status": "error", "reason": "no_db_factory"}

    async with db_factory() as db:
        return await _process_ai_job_inner(db, ai_job_id)


# ── Knowledge Ingestion (Phase 3) ─────────────────────────────────────────────

async def _process_knowledge_ingestion_inner(db: AsyncSession, file_id: str) -> dict:
    """
    Core ingestion logic for a single knowledge file.
    Testable without a running Redis/ARQ instance.
    """
    from app.services.knowledge_service import ingest_knowledge_file
    file_uuid = uuid.UUID(file_id)
    return await ingest_knowledge_file(db, file_uuid)


async def process_knowledge_ingestion(ctx: dict, file_id: str) -> dict:
    """
    ARQ task: ingest a knowledge file (extract → chunk → embed → store).

    ctx must contain 'db_session_factory'.
    """
    db_factory = ctx.get("db_session_factory")
    if db_factory is None:
        logger.error("worker_missing_db_factory", file_id=file_id)
        return {"status": "error", "reason": "no_db_factory"}

    async with db_factory() as db:
        return await _process_knowledge_ingestion_inner(db, file_id)


# ── Outbound Delivery (Phase 4) ───────────────────────────────────────────────

async def _process_outbound_message_inner(db: AsyncSession, message_id: str) -> dict:
    """
    Core outbound delivery logic.
    Testable without a running Redis/ARQ instance.
    """
    from app.services.outbound_service import deliver_outbound_message
    msg_uuid = uuid.UUID(message_id)
    return await deliver_outbound_message(db, msg_uuid)


async def process_outbound_message(ctx: dict, message_id: str) -> dict:
    """
    ARQ task: deliver a single outbound message via the configured provider.

    ctx must contain 'db_session_factory'.
    """
    db_factory = ctx.get("db_session_factory")
    if db_factory is None:
        logger.error("worker_missing_db_factory", message_id=message_id)
        return {"status": "error", "reason": "no_db_factory"}

    async with db_factory() as db:
        return await _process_outbound_message_inner(db, message_id)
