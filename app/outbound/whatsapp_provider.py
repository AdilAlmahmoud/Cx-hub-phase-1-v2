"""
WhatsApp outbound provider stub — Phase 4.

Plug in Meta Cloud API or Twilio WhatsApp by implementing the `send()` method.
Provider credentials should be stored in ChannelConfig.provider_config for the tenant.

TODO (Phase 5+):
  - Read phone_number_id and access_token from ChannelConfig.provider_config
  - Call POST https://graph.facebook.com/v18.0/{phone_number_id}/messages
  - Handle rate limits, template messages, and delivery receipts
"""
import time
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.outbound.base import BaseOutboundProvider, OutboundResult

if TYPE_CHECKING:
    from app.models.outbound import OutboundMessage

logger = get_logger(__name__)


class WhatsAppOutboundProvider(BaseOutboundProvider):
    """Stub: logs intent; real Meta/Twilio API call goes here."""

    @property
    def provider_name(self) -> str:
        return "whatsapp_stub"

    @property
    def channel(self) -> str:
        return "whatsapp"

    async def send(self, message: "OutboundMessage") -> OutboundResult:
        start = time.monotonic()
        logger.info(
            "outbound_whatsapp_stub",
            recipient=message.recipient_identifier,
            message_id=str(message.id),
            note="WhatsApp provider not configured — integrate Meta Cloud API or Twilio",
        )
        return OutboundResult(
            success=False,
            provider=self.provider_name,
            error_code="provider_not_configured",
            error_message="WhatsApp real provider not implemented. Set OUTBOUND_PROVIDER=mock for local mode.",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def health_check(self) -> bool:
        return False
