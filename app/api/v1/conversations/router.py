import uuid
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DB, CurrentTenant, AgentOrOwner
from app.models.conversation import ConversationStatus
from app.models.event_log import EventLog
from app.schemas.conversation import ConversationUpdate, ConversationResponse, ConversationDetailResponse, ConversationFilter
from app.schemas.event_log import EventLogResponse
from app.schemas.common import PaginatedResponse
from app.services.conversation_service import conversation_service

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get("", response_model=PaginatedResponse[ConversationResponse])
async def list_conversations(
    db: DB,
    current_tenant: CurrentTenant,
    _: AgentOrOwner,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: ConversationStatus | None = Query(None),
    channel: str | None = Query(None),
    customer_id: uuid.UUID | None = Query(None),
):
    """List conversations for the current tenant with filters."""
    filters = ConversationFilter(status=status, channel=channel, customer_id=customer_id)
    conversations, total = await conversation_service.get_all(
        db,
        tenant_id=current_tenant.id,
        skip=(page - 1) * page_size,
        limit=page_size,
        filters=filters,
    )
    return PaginatedResponse.create(
        items=[ConversationResponse.model_validate(c) for c in conversations],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: uuid.UUID, db: DB, current_tenant: CurrentTenant, _: AgentOrOwner
):
    """Get a conversation with customer detail."""
    conversation = await conversation_service.get_with_customer(db, conversation_id, current_tenant.id)
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return ConversationDetailResponse.model_validate(conversation)


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    db: DB,
    current_tenant: CurrentTenant,
    _: AgentOrOwner,
):
    """Update conversation status or subject."""
    conversation = await conversation_service.get_by_id(db, conversation_id, current_tenant.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation = await conversation_service.update(db, conversation, body)
    return ConversationResponse.model_validate(conversation)


@router.get("/{conversation_id}/events", response_model=PaginatedResponse[EventLogResponse])
async def list_conversation_events(
    conversation_id: uuid.UUID,
    db: DB,
    current_tenant: CurrentTenant,
    _: AgentOrOwner,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """List all events (messages) for a conversation."""
    conversation = await conversation_service.get_by_id(db, conversation_id, current_tenant.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    from sqlalchemy import func
    offset = (page - 1) * page_size
    total_result = await db.execute(
        select(func.count()).select_from(EventLog).where(
            EventLog.conversation_id == conversation_id,
            EventLog.tenant_id == current_tenant.id,
        )
    )
    total = total_result.scalar_one()
    events_result = await db.execute(
        select(EventLog)
        .where(EventLog.conversation_id == conversation_id, EventLog.tenant_id == current_tenant.id)
        .offset(offset)
        .limit(page_size)
        .order_by(EventLog.event_timestamp.asc())
    )
    events = events_result.scalars().all()
    return PaginatedResponse.create(
        items=[EventLogResponse.model_validate(e) for e in events],
        total=total,
        page=page,
        page_size=page_size,
    )
