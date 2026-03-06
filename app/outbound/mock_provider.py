"""
Mock outbound provider — Phase 4.

Handles all channels in local/development mode.
Logs delivery to the structured logger instead of calling a real API.
Always returns success, making it safe for automated tests and demos.

Activate by setting OUTBOUND_PROVIDER=mock (default).
"""
import time
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.outbound.base import BaseOutboundProvider, OutboundResult

if TYPE_CHECKING:
    from app.models.outbound import OutboundMessage

logger = get_logger(__name__)


class MockOutboundProvider(BaseOutboundProvider):
    """
    No-op provider that logs outbound messages without delivering them.
    Used in development, CI, and demonstration environments.
    """

    def __init__(self, channel: str) -> None:
        self._channel = channel

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def channel(self) -> str:
        return self._channel

    async def send(self, message: "OutboundMessage") -> OutboundResult:
        start = time.monotonic()

        logger.info(
            "outbound_mock_delivery",
            channel=message.channel,
            recipient=message.recipient_identifier,
            message_id=str(message.id),
            tenant_id=str(message.tenant_id),
            is_ai_generated=message.is_ai_generated,
            message_preview=(message.message_text or "")[:120],
        )

        duration_ms = int((time.monotonic() - start) * 1000)
        mock_provider_id = f"mock_{message.id}"

        return OutboundResult(
            success=True,
            provider=self.provider_name,
            provider_message_id=mock_provider_id,
            duration_ms=duration_ms,
            raw_response={"mock": True, "provider_message_id": mock_provider_id},
        )

    async def health_check(self) -> bool:
        return True
