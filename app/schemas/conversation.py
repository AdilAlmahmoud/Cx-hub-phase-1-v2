import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
from app.models.conversation import ConversationStatus
from app.schemas.customer import CustomerResponse


class ConversationCreate(BaseModel):
    customer_id: uuid.UUID
    channel: str
    subject: Optional[str] = None


class ConversationUpdate(BaseModel):
    status: Optional[ConversationStatus] = None
    subject: Optional[str] = None


class ConversationFilter(BaseModel):
    status: Optional[ConversationStatus] = None
    channel: Optional[str] = None
    customer_id: Optional[uuid.UUID] = None


class ConversationResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    customer_id: uuid.UUID
    channel: str
    status: ConversationStatus
    subject: Optional[str]
    last_message_preview: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetailResponse(ConversationResponse):
    customer: Optional[CustomerResponse] = None
