"""
Outbound Message models — Phase 4.

OutboundMessage represents a single message to be delivered to a customer.
OutboundAttempt records each delivery attempt (provider call + result).

Lifecycle:
  pending → sending → delivered
                  \→ failed  (attempt_count < max_attempts, will retry)
                  \→ failed  (attempt_count >= max_attempts, permanent)

Cancelled: messages abandoned before first send (e.g. superseded by human agent).
"""
import uuid
import enum
from typing import Optional, TYPE_CHECKING
from datetime import datetime

from sqlalchemy import (
    String, Boolean, Text, Integer, ForeignKey,
    Enum as SAEnum, DateTime, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.conversation import Conversation
    from app.models.ticket import Ticket
    from app.models.user import User
    from app.models.ai_result import AIResult


class OutboundMessageStatus(str, enum.Enum):
    pending = "pending"
    sending = "sending"
    delivered = "delivered"
    failed = "failed"
    cancelled = "cancelled"


class OutboundMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "outbound_messages"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ticket_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # Link to the AI result that triggered this send (null for manual sends)
    ai_result_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_results.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Agent who manually sent (null for AI-triggered sends)
    sent_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    channel: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # Channel-specific address: phone number, email, session_id, etc.
    recipient_identifier: Mapped[str] = mapped_column(String(500), nullable=False)

    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    # For email: Subject line
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    message_type: Mapped[str] = mapped_column(String(50), default="text", nullable=False)

    status: Mapped[OutboundMessageStatus] = mapped_column(
        SAEnum(OutboundMessageStatus), default=OutboundMessageStatus.pending, nullable=False, index=True,
    )
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Extra metadata (e.g. email headers, template variables, etc.)
    extra_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    attempts: Mapped[list["OutboundAttempt"]] = relationship(
        "OutboundAttempt", back_populates="message", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<OutboundMessage id={self.id} channel={self.channel} status={self.status}>"


class OutboundAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "outbound_attempts"

    outbound_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outbound_messages.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), default="mock", nullable=False)

    # "success" | "failure"
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    raw_response: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    message: Mapped["OutboundMessage"] = relationship("OutboundMessage", back_populates="attempts")

    def __repr__(self) -> str:
        return f"<OutboundAttempt id={self.id} attempt={self.attempt_number} status={self.status}>"
