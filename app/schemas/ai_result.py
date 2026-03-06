"""Pydantic schemas for AIResult (response DTOs)."""
import uuid
from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel


class AIResultResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    ai_job_id: uuid.UUID
    ticket_id: uuid.UUID

    # Structured decision
    intent: Optional[str]
    answer: Optional[str]          # draft reply candidate (not sent in Phase 2)
    confidence: Optional[float]
    should_escalate: bool
    risk_flags: Optional[List[str]]
    escalation_reason: Optional[str]
    safe_to_auto_send: bool
    processing_notes: Optional[str]

    # Provider metadata
    provider_name: str
    model_name: Optional[str]
    processing_duration_ms: Optional[int]

    # Phase 3: RAG metadata
    retrieved_chunk_ids: Optional[List[str]] = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
