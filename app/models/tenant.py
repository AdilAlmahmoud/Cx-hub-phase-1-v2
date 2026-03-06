import uuid
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Boolean, Text, Float, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.customer import Customer
    from app.models.conversation import Conversation
    from app.models.ticket import Ticket
    from app.models.event_log import EventLog


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(50), default="starter", nullable=False)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    config: Mapped[Optional["TenantConfig"]] = relationship(
        "TenantConfig", back_populates="tenant", uselist=False, cascade="all, delete-orphan"
    )
    channel_configs: Mapped[List["ChannelConfig"]] = relationship(
        "ChannelConfig", back_populates="tenant", cascade="all, delete-orphan"
    )
    users: Mapped[List["User"]] = relationship(
        "User", back_populates="tenant", cascade="all, delete-orphan"
    )
    customers: Mapped[List["Customer"]] = relationship(
        "Customer", back_populates="tenant", cascade="all, delete-orphan"
    )
    conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation", back_populates="tenant", cascade="all, delete-orphan"
    )
    tickets: Mapped[List["Ticket"]] = relationship(
        "Ticket", back_populates="tenant", cascade="all, delete-orphan"
    )
    event_logs: Mapped[List["EventLog"]] = relationship(
        "EventLog", back_populates="tenant", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} slug={self.slug}>"


class TenantConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenant_configs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_assign: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    business_hours: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    custom_settings: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # ── Phase 2: AI policy fields ──────────────────────────────────────────────
    # Language the AI should reply in (ISO 639-1)
    ai_language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    # Tone for AI-generated replies
    ai_tone: Mapped[str] = mapped_column(String(50), default="professional", nullable=False)
    # Minimum confidence required for safe_to_auto_send=True
    confidence_threshold: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    # "off" | "supervised" | "auto"
    auto_send_mode: Mapped[str] = mapped_column(String(20), default="off", nullable=False)
    # List of keywords that always trigger escalation
    escalation_keywords: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Template message sent to customer when handing off to human agent
    handoff_message_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="config")

    def __repr__(self) -> str:
        return f"<TenantConfig tenant_id={self.tenant_id}>"


class ChannelConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "channel_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel", name="uq_tenant_channel"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    webhook_secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationship
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="channel_configs")

    def __repr__(self) -> str:
        return f"<ChannelConfig tenant_id={self.tenant_id} channel={self.channel}>"
