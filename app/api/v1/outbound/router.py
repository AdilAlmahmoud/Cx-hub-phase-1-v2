"""
Outbound Messaging API — Phase 4.

Endpoints:
  POST /outbound/send          - Manually send a message to a customer
  GET  /outbound               - List outbound messages (paginated)
  GET  /outbound/{id}          - Get message detail (with attempts)
  POST /outbound/{id}/cancel   - Cancel a pending message
  GET  /outbound/{id}/attempts - Get delivery attempts for a message
"""
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DB, CurrentTenant, AgentOrOwner
from app.core.logging import get_logger
from app.core.queue import enqueue_outbound_message
from app.models.conversation import Conversation
from app.schemas.outbound import (
    OutboundSendRequest,
    OutboundMessageResponse,
    OutboundMessageDetailResponse,
    OutboundMessageListResponse,
    OutboundAttemptResponse,
)
from app.services.outbound_service import (
    create_outbound_message,
    get_outbound_message,
    list_outbound_messages,
    list_outbound_attempts,
    cancel_outbound_message,
)
from sqlalchemy import select

logger = get_logger(__name__)
router = APIRouter(prefix="/outbound", tags=["Outbound Messaging"])


@router.post("/send", response_model=OutboundMessageResponse, status_code=status.HTTP_202_ACCEPTED)
async def send_outbound_message(
    body: OutboundSendRequest,
    db: DB,
    current_tenant: CurrentTenant,
    current_user: AgentOrOwner,
):
    """
    Queue an outbound message for delivery to the customer in a conversation.

    The message is persisted immediately and delivered asynchronously.
    Returns 202 Accepted with the message record.
    """
    # Resolve conversation — must belong to this tenant
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == body.conversation_id,
            Conversation.tenant_id == current_tenant.id,
        )
    )
    conversation = conv_result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # Derive recipient from customer's external_id + channel
    # Load the customer record linked to this conversation
    from app.models.customer import Customer
    cust_result = await db.execute(
        select(Customer).where(Customer.id == conversation.customer_id)
    )
    customer = cust_result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    msg = await create_outbound_message(
        db=db,
        tenant_id=current_tenant.id,
        conversation_id=conversation.id,
        channel=conversation.channel,
        recipient_identifier=customer.external_id,
        message_text=body.message_text,
        sent_by_user_id=current_user.id,
        is_ai_generated=False,
        subject=body.subject,
        message_type=body.message_type,
    )

    await enqueue_outbound_message(str(msg.id))

    logger.info(
        "outbound_message_queued",
        message_id=str(msg.id),
        tenant_id=str(current_tenant.id),
        conversation_id=str(conversation.id),
        channel=conversation.channel,
    )
    return OutboundMessageResponse.model_validate(msg)


@router.get("", response_model=OutboundMessageListResponse)
async def list_messages(
    db: DB,
    current_tenant: CurrentTenant,
    _user: AgentOrOwner,
    conversation_id: Optional[uuid.UUID] = Query(None),
    ticket_id: Optional[uuid.UUID] = Query(None),
    outbound_status: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List outbound messages for this tenant (paginated, filterable)."""
    skip = (page - 1) * page_size
    items, total = await list_outbound_messages(
        db=db,
        tenant_id=current_tenant.id,
        conversation_id=conversation_id,
        ticket_id=ticket_id,
        status=outbound_status,
        skip=skip,
        limit=page_size,
    )
    return OutboundMessageListResponse(
        items=[OutboundMessageResponse.model_validate(m) for m in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{message_id}", response_model=OutboundMessageDetailResponse)
async def get_message(
    message_id: uuid.UUID,
    db: DB,
    current_tenant: CurrentTenant,
    _user: AgentOrOwner,
):
    """Get a single outbound message with all delivery attempts."""
    msg = await get_outbound_message(db, message_id, current_tenant.id)
    if not msg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    attempts = await list_outbound_attempts(db, message_id, current_tenant.id)
    attempt_responses = [OutboundAttemptResponse.model_validate(a) for a in attempts]
    base = OutboundMessageResponse.model_validate(msg)
    return OutboundMessageDetailResponse(
        **base.model_dump(),
        attempts=attempt_responses,
    )


@router.get("/{message_id}/attempts", response_model=list[OutboundAttemptResponse])
async def get_attempts(
    message_id: uuid.UUID,
    db: DB,
    current_tenant: CurrentTenant,
    _user: AgentOrOwner,
):
    """Get delivery attempts for an outbound message."""
    msg = await get_outbound_message(db, message_id, current_tenant.id)
    if not msg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    attempts = await list_outbound_attempts(db, message_id, current_tenant.id)
    return [OutboundAttemptResponse.model_validate(a) for a in attempts]


@router.post("/{message_id}/cancel", response_model=OutboundMessageResponse)
async def cancel_message(
    message_id: uuid.UUID,
    db: DB,
    current_tenant: CurrentTenant,
    _user: AgentOrOwner,
):
    """Cancel a pending outbound message (cannot cancel delivered messages)."""
    msg = await cancel_outbound_message(db, message_id, current_tenant.id)
    if not msg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return OutboundMessageResponse.model_validate(msg)
