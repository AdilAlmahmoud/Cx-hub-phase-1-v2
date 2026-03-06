"""
AIResult model — stores the structured output of a completed AI job.

One AIResult is created per successfully completed AIJob.
The 'answer' field holds the draft reply candidate (not sent in Phase 2).
"""
import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, Float, Boolean, Text, ForeignKey, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.ai_job import AIJob


class AIResult(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_results"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 1-to-1 with AIJob
    ai_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_jobs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Structured AI decision ─────────────────────────────────────────────────
    intent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # draft reply candidate
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    should_escalate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    risk_flags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    escalation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    safe_to_auto_send: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    processing_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Provider metadata ──────────────────────────────────────────────────────
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    processing_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_provider_response: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationship
    ai_job: Mapped["AIJob"] = relationship("AIJob", back_populates="ai_result")

    def __repr__(self) -> str:
        return (
            f"<AIResult id={self.id} intent={self.intent} "
            f"safe={self.safe_to_auto_send} escalate={self.should_escalate}>"
        )
