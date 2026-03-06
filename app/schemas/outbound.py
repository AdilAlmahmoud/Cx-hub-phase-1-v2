"""Pydantic schemas for outbound message API — Phase 4."""
import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class OutboundSendRequest(BaseModel):
    """Request body for manually sending an outbound message."""
    conversation_id: uuid.UUID
    message_text: str = Field(..., min_length=1, max_length=4096)
    # Optional subject for email channel
    subject: Optional[str] = Field(None, max_length=500)
    message_type: str = Field(default="text", max_length=50)


class OutboundAttemptResponse(BaseModel):
    id: uuid.UUID
    outbound_message_id: uuid.UUID
    attempt_number: int
    provider: str
    status: str
    provider_message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    attempted_at: datetime
    duration_ms: Optional[int] = None

    model_config = {"from_attributes": True}


class OutboundMessageResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    ticket_id: Optional[uuid.UUID] = None
    ai_result_id: Optional[uuid.UUID] = None
    sent_by_user_id: Optional[uuid.UUID] = None

    channel: str
    recipient_identifier: str
    message_text: str
    subject: Optional[str] = None
    message_type: str
    status: str
    is_ai_generated: bool

    attempt_count: int
    max_attempts: int
    provider_message_id: Optional[str] = None
    last_error: Optional[str] = None

    scheduled_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OutboundMessageDetailResponse(OutboundMessageResponse):
    attempts: List[OutboundAttemptResponse] = []


class OutboundMessageListResponse(BaseModel):
    items: List[OutboundMessageResponse]
    total: int
    page: int
    page_size: int
