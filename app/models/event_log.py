import uuid
from typing import Optional, TYPE_CHECKING
from datetime import datetime
from sqlalchemy import String, ForeignKey, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.conversation import Conversation


class EventLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Unified internal event model. Every inbound message from any channel
    is normalized into an EventLog entry.
    """
    __tablename__ = "event_logs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Unified event fields
    channel: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    external_user_identifier: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    message_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    event_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    direction: Mapped[str] = mapped_column(String(20), default="inbound", nullable=False)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="event_logs")
    conversation: Mapped[Optional["Conversation"]] = relationship(
        "Conversation", back_populates="event_logs"
    )

    def __repr__(self) -> str:
        return f"<EventLog id={self.id} channel={self.channel} direction={self.direction}>"
