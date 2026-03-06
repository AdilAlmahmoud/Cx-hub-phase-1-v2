"""
Outbound provider registry — Phase 4.

`get_outbound_provider(channel)` returns the right provider based on
the OUTBOUND_PROVIDER environment setting.

When OUTBOUND_PROVIDER=mock (default), all channels use MockOutboundProvider.
When OUTBOUND_PROVIDER=real, each channel gets its own real provider stub.
"""
from app.core.config import settings
from app.core.logging import get_logger
from app.outbound.base import BaseOutboundProvider
from app.outbound.mock_provider import MockOutboundProvider

logger = get_logger(__name__)

_VALID_CHANNELS = {"whatsapp", "webchat", "sms", "email"}


def get_outbound_provider(channel: str) -> BaseOutboundProvider:
    """
    Return an outbound provider for the given channel.

    In mock mode (OUTBOUND_PROVIDER=mock), always returns MockOutboundProvider.
    In real mode, returns the channel-specific stub/implementation.
    """
    channel = channel.lower()

    if settings.OUTBOUND_PROVIDER == "mock" or channel not in _VALID_CHANNELS:
        return MockOutboundProvider(channel=channel)

    # Real channel stubs — integrate actual providers here
    if channel == "whatsapp":
        from app.outbound.whatsapp_provider import WhatsAppOutboundProvider
        return WhatsAppOutboundProvider()
    if channel == "sms":
        from app.outbound.sms_provider import SMSOutboundProvider
        return SMSOutboundProvider()
    if channel == "email":
        from app.outbound.email_provider import EmailOutboundProvider
        return EmailOutboundProvider()
    if channel == "webchat":
        from app.outbound.webchat_provider import WebChatOutboundProvider
        return WebChatOutboundProvider()

    # Fallback: use mock for unknown channels
    logger.warning("outbound_unknown_channel_using_mock", channel=channel)
    return MockOutboundProvider(channel=channel)
