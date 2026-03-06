"""
Email outbound provider stub — Phase 4.

Plug in SMTP, SendGrid, AWS SES, or Mailgun by implementing `send()`.
Provider credentials should be stored in ChannelConfig.provider_config for the tenant.

TODO (Phase 5+):
  - Read smtp_host, smtp_port, smtp_user, smtp_password from ChannelConfig.provider_config
    or read SENDGRID_API_KEY / AWS_SES credentials from environment
  - Use aiosmtplib or sendgrid-python / boto3 SES to send
  - Populate OutboundMessage.subject as the email subject line
  - Handle bounce callbacks and delivery receipts
"""
import time
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.outbound.base import BaseOutboundProvider, OutboundResult

if TYPE_CHECKING:
    from app.models.outbound import OutboundMessage

logger = get_logger(__name__)


class EmailOutboundProvider(BaseOutboundProvider):
    """Stub: logs intent; real SMTP/SendGrid/SES call goes here."""

    @property
    def provider_name(self) -> str:
        return "email_stub"

    @property
    def channel(self) -> str:
        return "email"

    async def send(self, message: "OutboundMessage") -> OutboundResult:
        start = time.monotonic()
        logger.info(
            "outbound_email_stub",
            recipient=message.recipient_identifier,
            subject=message.subject,
            message_id=str(message.id),
            note="Email provider not configured — integrate SMTP/SendGrid/SES",
        )
        return OutboundResult(
            success=False,
            provider=self.provider_name,
            error_code="provider_not_configured",
            error_message="Email real provider not implemented. Set OUTBOUND_PROVIDER=mock for local mode.",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def health_check(self) -> bool:
        return False
