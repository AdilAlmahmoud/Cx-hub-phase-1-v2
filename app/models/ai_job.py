"""
AIJob model — tracks the lifecycle of a single AI processing job.

One AIJob is created per inbound message (when ai_enabled=True for the tenant).
The job passes through statuses: pending → processing → completed | failed.
"""
import uuid
import enum
from typing import Optional, TYPE_CHECKING
from datetime import datetime

from sqlalchemy import String, Integer, Text, ForeignKey, Enum as SAEnum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.ai_result import AIResult


class AIJobStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class AIJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_jobs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_log_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_logs.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[AIJobStatus] = mapped_column(
        SAEnum(AIJobStatus, name="aijobstatus"),
        nullable=False,
        default=AIJobStatus.pending,
        index=True,
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # One-to-one back-ref to the result (populated once the job completes)
    ai_result: Mapped[Optional["AIResult"]] = relationship(
        "AIResult", back_populates="ai_job", uselist=False
    )

    def __repr__(self) -> str:
        return f"<AIJob id={self.id} status={self.status} retry={self.retry_count}>"
