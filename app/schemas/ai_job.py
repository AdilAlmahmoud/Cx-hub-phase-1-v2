"""Pydantic schemas for AIJob (request/response DTOs)."""
import uuid
from typing import Optional
from datetime import datetime

from pydantic import BaseModel

from app.models.ai_job import AIJobStatus


class AIJobResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    ticket_id: uuid.UUID
    conversation_id: uuid.UUID
    event_log_id: Optional[uuid.UUID]
    status: AIJobStatus
    retry_count: int
    max_retries: int
    error_message: Optional[str]
    scheduled_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AIJobRetryResponse(BaseModel):
    """Returned when a retry is successfully scheduled."""
    ai_job_id: uuid.UUID
    message: str
    new_status: AIJobStatus
