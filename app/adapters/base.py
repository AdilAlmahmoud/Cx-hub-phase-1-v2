"""
Channel Adapter Layer - Base classes and Unified Event model.

Every inbound message from any channel is normalized into a UnifiedEvent
before further processing. This decouples channel-specific payload formats
from the core domain logic.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
import uuid


class ChannelType(str, Enum):
    whatsapp = "whatsapp"
    webchat = "webchat"
    sms = "sms"


class UnifiedEvent(BaseModel):
    """
    Normalized internal representation of any inbound message.
    All channel adapters must produce this model.
    """
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    channel: ChannelType
    external_user_identifier: str
    message_text: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload: Optional[dict] = None
    metadata: Optional[dict] = None

    model_config = {"use_enum_values": True}


class BaseChannelAdapter(ABC):
    """
    Abstract base for all channel adapters.
    Subclasses translate channel-specific payloads into UnifiedEvent objects.
    """
    channel: ChannelType

    @abstractmethod
    def normalize(self, tenant_id: str, payload: dict[str, Any]) -> UnifiedEvent:
        """
        Transform a raw channel payload into a UnifiedEvent.

        Args:
            tenant_id: The tenant this message belongs to.
            payload: Raw HTTP payload from the channel provider.

        Returns:
            A normalized UnifiedEvent.
        """
        ...

    def validate_payload(self, payload: dict[str, Any]) -> bool:
        """
        Optional payload validation hook. Override in subclasses.
        Returns True if the payload is valid.
        """
        return True
