import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
from app.models.ticket import TicketStatus, TicketPriority
from app.schemas.user import UserResponse


class TicketCreate(BaseModel):
    conversation_id: uuid.UUID
    title: Optional[str] = None
    priority: TicketPriority = TicketPriority.medium
    notes: Optional[str] = None


class TicketUpdate(BaseModel):
    assigned_agent_id: Optional[uuid.UUID] = None
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    title: Optional[str] = None
    notes: Optional[str] = None


class TicketFilter(BaseModel):
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    assigned_agent_id: Optional[uuid.UUID] = None


class TicketResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    assigned_agent_id: Optional[uuid.UUID]
    status: TicketStatus
    priority: TicketPriority
    title: Optional[str]
    notes: Optional[str]
    ticket_number: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TicketDetailResponse(TicketResponse):
    assigned_agent: Optional[UserResponse] = None
