"""
Outbound message service — Phase 4.

Business logic for creating, delivering, and tracking outbound messages.
Delivery is async (via ARQ worker task) so API calls return immediately.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.outbound import OutboundMessage, OutboundAttempt, OutboundMessageStatus

logger = get_logger(__name__)


async def create_outbound_message(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    channel: str,
    recipient_identifier: str,
    message_text: str,
    *,
    ticket_id: Optional[uuid.UUID] = None,
    ai_result_id: Optional[uuid.UUID] = None,
    sent_by_user_id: Optional[uuid.UUID] = None,
    is_ai_generated: bool = False,
    subject: Optional[str] = None,
    message_type: str = "text",
    extra_metadata: Optional[dict] = None,
) -> OutboundMessage:
    """
    Create and persist an OutboundMessage record (status=pending).
    Caller is responsible for enqueuing the delivery job.
    """
    msg = OutboundMessage(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        ticket_id=ticket_id,
        ai_result_id=ai_result_id,
        sent_by_user_id=sent_by_user_id,
        channel=channel,
        recipient_identifier=recipient_identifier,
        message_text=message_text,
        subject=subject,
        message_type=message_type,
        is_ai_generated=is_ai_generated,
        status=OutboundMessageStatus.pending,
        attempt_count=0,
        extra_metadata=extra_metadata,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    logger.info(
        "outbound_message_created",
        message_id=str(msg.id),
        tenant_id=str(tenant_id),
        channel=channel,
        is_ai_generated=is_ai_generated,
    )
    return msg


async def deliver_outbound_message(
    db: AsyncSession,
    message_id: uuid.UUID,
) -> dict:
    """
    Attempt delivery of an OutboundMessage via the configured provider.
    Records an OutboundAttempt regardless of outcome.

    Returns a dict with status, message_id, and provider details.
    """
    import time
    from app.outbound.registry import get_outbound_provider

    result_row = await db.execute(
        select(OutboundMessage).where(OutboundMessage.id == message_id)
    )
    msg: Optional[OutboundMessage] = result_row.scalar_one_or_none()

    if msg is None:
        return {"status": "not_found", "message_id": str(message_id)}

    if msg.status in (OutboundMessageStatus.delivered, OutboundMessageStatus.cancelled):
        return {"status": "skipped", "reason": msg.status.value, "message_id": str(message_id)}

    if msg.attempt_count >= msg.max_attempts:
        msg.status = OutboundMessageStatus.failed
        await db.commit()
        return {"status": "failed", "reason": "max_attempts_exceeded", "message_id": str(message_id)}

    # Mark as sending
    msg.status = OutboundMessageStatus.sending
    msg.attempt_count += 1
    await db.commit()

    attempt_number = msg.attempt_count
    started = datetime.now(timezone.utc)

    try:
        provider = get_outbound_provider(msg.channel)
        start_mono = time.monotonic()
        result = await provider.send(msg)
        duration_ms = result.duration_ms or int((time.monotonic() - start_mono) * 1000)
    except Exception as exc:
        # Unexpected provider error
        duration_ms = 0
        from app.outbound.base import OutboundResult
        result = OutboundResult(
            success=False,
            provider="unknown",
            error_code="provider_exception",
            error_message=str(exc)[:500],
            duration_ms=0,
        )

    # Record attempt
    attempt = OutboundAttempt(
        id=uuid.uuid4(),
        outbound_message_id=msg.id,
        tenant_id=msg.tenant_id,
        attempt_number=attempt_number,
        provider=result.provider,
        status="success" if result.success else "failure",
        provider_message_id=result.provider_message_id,
        error_code=result.error_code,
        error_message=result.error_message,
        attempted_at=started,
        duration_ms=duration_ms,
        raw_response=result.raw_response,
    )
    db.add(attempt)

    # Update message status
    if result.success:
        msg.status = OutboundMessageStatus.delivered
        msg.sent_at = started
        msg.delivered_at = datetime.now(timezone.utc)
        msg.provider_message_id = result.provider_message_id
        msg.last_error = None
    else:
        msg.last_error = result.error_message
        if msg.attempt_count >= msg.max_attempts:
            msg.status = OutboundMessageStatus.failed
        else:
            msg.status = OutboundMessageStatus.pending  # will be retried

    await db.commit()

    logger.info(
        "outbound_delivery_attempt",
        message_id=str(msg.id),
        tenant_id=str(msg.tenant_id),
        attempt=attempt_number,
        provider=result.provider,
        success=result.success,
        duration_ms=duration_ms,
    )

    return {
        "status": msg.status.value,
        "message_id": str(msg.id),
        "provider": result.provider,
        "success": result.success,
        "provider_message_id": result.provider_message_id,
        "error": result.error_message,
    }


async def get_outbound_message(
    db: AsyncSession,
    message_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> Optional[OutboundMessage]:
    result = await db.execute(
        select(OutboundMessage).where(
            OutboundMessage.id == message_id,
            OutboundMessage.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def list_outbound_messages(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    conversation_id: Optional[uuid.UUID] = None,
    ticket_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[List[OutboundMessage], int]:
    query = select(OutboundMessage).where(OutboundMessage.tenant_id == tenant_id)
    count_query = select(func.count()).select_from(OutboundMessage).where(
        OutboundMessage.tenant_id == tenant_id
    )

    if conversation_id:
        query = query.where(OutboundMessage.conversation_id == conversation_id)
        count_query = count_query.where(OutboundMessage.conversation_id == conversation_id)
    if ticket_id:
        query = query.where(OutboundMessage.ticket_id == ticket_id)
        count_query = count_query.where(OutboundMessage.ticket_id == ticket_id)
    if status:
        query = query.where(OutboundMessage.status == status)
        count_query = count_query.where(OutboundMessage.status == status)

    query = query.order_by(OutboundMessage.created_at.desc()).offset(skip).limit(limit)

    rows = (await db.execute(query)).scalars().all()
    total = (await db.execute(count_query)).scalar_one()
    return list(rows), total


async def list_outbound_attempts(
    db: AsyncSession,
    message_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> List[OutboundAttempt]:
    result = await db.execute(
        select(OutboundAttempt).where(
            OutboundAttempt.outbound_message_id == message_id,
            OutboundAttempt.tenant_id == tenant_id,
        ).order_by(OutboundAttempt.attempt_number.asc())
    )
    return list(result.scalars().all())


async def cancel_outbound_message(
    db: AsyncSession,
    message_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> Optional[OutboundMessage]:
    msg = await get_outbound_message(db, message_id, tenant_id)
    if not msg:
        return None
    if msg.status in (OutboundMessageStatus.delivered, OutboundMessageStatus.cancelled):
        return msg
    msg.status = OutboundMessageStatus.cancelled
    await db.commit()
    await db.refresh(msg)
    return msg
