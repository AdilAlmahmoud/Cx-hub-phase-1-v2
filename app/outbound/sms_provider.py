"""
SMS outbound provider stub — Phase 4.

Plug in Twilio, Vonage, or AWS SNS by implementing the `send()` method.
Provider credentials should be stored in ChannelConfig.provider_config for the tenant.

TODO (Phase 5+):
  - Read account_sid, auth_token, from_number from ChannelConfig.provider_config
  - Call Twilio Messages API (POST https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json)
  - Handle delivery status callbacks
"""
import time
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.outbound.base import BaseOutboundProvider, OutboundResult

if TYPE_CHECKING:
    from app.models.outbound import OutboundMessage

logger = get_logger(__name__)


class SMSOutboundProvider(BaseOutboundProvider):
    """Stub: logs intent; real Twilio/Vonage API call goes here."""

    @property
    def provider_name(self) -> str:
        return "sms_stub"

    @property
    def channel(self) -> str:
        return "sms"

    async def send(self, message: "OutboundMessage") -> OutboundResult:
        start = time.monotonic()
        logger.info(
            "outbound_sms_stub",
            recipient=message.recipient_identifier,
            message_id=str(message.id),
            note="SMS provider not configured — integrate Twilio/Vonage",
        )
        return OutboundResult(
            success=False,
            provider=self.provider_name,
            error_code="provider_not_configured",
            error_message="SMS real provider not implemented. Set OUTBOUND_PROVIDER=mock for local mode.",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def health_check(self) -> bool:
        return False
