"""
Outbound provider abstraction layer — Phase 4.

All channel outbound providers implement BaseOutboundProvider.
This allows swapping mock providers for real ones (Twilio, SendGrid, Meta Cloud API)
without touching business logic.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.outbound import OutboundMessage


@dataclass
class OutboundResult:
    """Result of a single outbound delivery attempt."""
    success: bool
    provider: str
    provider_message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: int = 0
    raw_response: Optional[dict] = field(default=None)


class BaseOutboundProvider(ABC):
    """
    Abstract base class for all outbound channel providers.

    Each provider handles a single channel type (whatsapp, sms, email, webchat).
    Subclasses must implement `send()` and `health_check()`.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short identifier: 'mock', 'twilio', 'sendgrid', 'meta', etc."""
        ...

    @property
    @abstractmethod
    def channel(self) -> str:
        """Channel this provider handles: 'whatsapp', 'sms', 'email', 'webchat'."""
        ...

    @abstractmethod
    async def send(self, message: "OutboundMessage") -> OutboundResult:
        """
        Deliver a single outbound message.

        Args:
            message: The OutboundMessage record to deliver.

        Returns:
            OutboundResult with success/failure details.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable and configured correctly."""
        ...
