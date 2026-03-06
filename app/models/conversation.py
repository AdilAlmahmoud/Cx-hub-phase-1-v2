import uuid
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, ForeignKey, Enum as SAEnum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.customer import Customer
    from app.models.ticket import Ticket
    from app.models.event_log import EventLog


class ConversationStatus(str, enum.Enum):
    open = "open"
    closed = "closed"


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[ConversationStatus] = mapped_column(
        SAEnum(ConversationStatus), default=ConversationStatus.open, nullable=False
    )
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_message_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="conversations")
    customer: Mapped["Customer"] = relationship("Customer", back_populates="conversations")
    ticket: Mapped[Optional["Ticket"]] = relationship(
        "Ticket", back_populates="conversation", uselist=False, cascade="all, delete-orphan"
    )
    event_logs: Mapped[List["EventLog"]] = relationship(
        "EventLog", back_populates="conversation"
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} channel={self.channel} status={self.status}>"
