"""
WebChat outbound provider stub — Phase 4.

Real delivery pushes a reply to the connected WebChat widget session.
Full implementation requires WebSocket push (Phase 5+).

TODO (Phase 5+):
  - Maintain an in-memory (or Redis-backed) registry of active WebSocket connections
    keyed by tenant_id + session_id
  - Push the message JSON over the WebSocket connection
  - Fall back to polling: store the message so the widget can retrieve it on next poll
"""
import time
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.outbound.base import BaseOutboundProvider, OutboundResult

if TYPE_CHECKING:
    from app.models.outbound import OutboundMessage

logger = get_logger(__name__)


class WebChatOutboundProvider(BaseOutboundProvider):
    """Stub: logs intent; WebSocket push goes here."""

    @property
    def provider_name(self) -> str:
        return "webchat_stub"

    @property
    def channel(self) -> str:
        return "webchat"

    async def send(self, message: "OutboundMessage") -> OutboundResult:
        start = time.monotonic()
        logger.info(
            "outbound_webchat_stub",
            recipient=message.recipient_identifier,
            message_id=str(message.id),
            note="WebChat push not configured — implement WebSocket layer",
        )
        return OutboundResult(
            success=False,
            provider=self.provider_name,
            error_code="provider_not_configured",
            error_message="WebChat push not implemented. Set OUTBOUND_PROVIDER=mock for local mode.",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def health_check(self) -> bool:
        return False
