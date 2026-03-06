"""
ARQ (asyncio Redis Queue) pool management.

Provides a thin wrapper around the ARQ Redis pool so the rest of the
application can enqueue AI jobs without direct coupling to ARQ internals.

If Redis is not available (e.g. in tests), pool stays None and
enqueue_ai_job() returns False without raising — the job row in the DB
remains in 'pending' status and can be picked up by a worker later.
"""
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_arq_pool = None  # type: Optional[object]  # arq.ArqRedis at runtime


async def init_queue() -> None:
    """
    Create the ARQ Redis connection pool.
    Called from FastAPI lifespan startup.
    No-op if AI_QUEUE_ENABLED=False.
    """
    global _arq_pool
    if not settings.AI_QUEUE_ENABLED:
        logger.info("ai_queue_disabled", reason="AI_QUEUE_ENABLED=False")
        return
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
        _arq_pool = await create_pool(redis_settings)
        logger.info("ai_queue_connected", redis_url=settings.REDIS_URL)
    except Exception as exc:
        # Non-fatal: API still serves traffic; jobs stay pending in DB
        logger.warning(
            "ai_queue_unavailable",
            error=str(exc),
            hint="Jobs will remain in 'pending' status until a worker connects",
        )
        _arq_pool = None


async def close_queue() -> None:
    """Close the ARQ pool. Called from FastAPI lifespan shutdown."""
    global _arq_pool
    if _arq_pool is not None:
        try:
            await _arq_pool.aclose()
        except Exception:
            pass
        _arq_pool = None
        logger.info("ai_queue_closed")


async def enqueue_ai_job(ai_job_id: str) -> bool:
    """
    Enqueue an AI processing job by ID.

    Returns True if successfully enqueued, False if pool is unavailable.
    The job row must already exist in the DB before calling this.
    """
    if _arq_pool is None:
        logger.warning(
            "ai_queue_not_available_skip_enqueue",
            ai_job_id=ai_job_id,
        )
        return False
    try:
        await _arq_pool.enqueue_job("process_ai_job", ai_job_id=ai_job_id)
        logger.info("ai_job_enqueued", ai_job_id=ai_job_id)
        return True
    except Exception as exc:
        logger.error("ai_job_enqueue_error", ai_job_id=ai_job_id, error=str(exc))
        return False


async def enqueue_knowledge_ingestion(file_id: str) -> bool:
    """
    Enqueue a knowledge file ingestion job by file ID.

    Returns True if successfully enqueued, False if pool is unavailable.
    The KnowledgeFile record must already exist in the DB before calling this.
    """
    if _arq_pool is None:
        logger.warning(
            "ai_queue_not_available_skip_enqueue",
            file_id=file_id,
        )
        return False
    try:
        await _arq_pool.enqueue_job("process_knowledge_ingestion", file_id=file_id)
        logger.info("knowledge_ingestion_enqueued", file_id=file_id)
        return True
    except Exception as exc:
        logger.error("knowledge_ingestion_enqueue_error", file_id=file_id, error=str(exc))
        return False


async def enqueue_outbound_message(message_id: str) -> bool:
    """
    Enqueue an outbound message delivery job by message ID.

    Returns True if successfully enqueued, False if pool is unavailable.
    The OutboundMessage record must already exist in the DB before calling this.
    """
    if _arq_pool is None:
        logger.warning(
            "ai_queue_not_available_skip_enqueue",
            message_id=message_id,
        )
        return False
    try:
        await _arq_pool.enqueue_job("process_outbound_message", message_id=message_id)
        logger.info("outbound_message_enqueued", message_id=message_id)
        return True
    except Exception as exc:
        logger.error("outbound_message_enqueue_error", message_id=message_id, error=str(exc))
        return False


def get_queue_pool():
    """Return the current ARQ pool (may be None)."""
    return _arq_pool
