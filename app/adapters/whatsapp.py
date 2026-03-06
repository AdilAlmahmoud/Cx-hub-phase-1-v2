"""
WhatsApp Channel Adapter.

Accepts a generic HTTP payload representing a WhatsApp message.
Real provider integration (e.g. Meta Cloud API, Twilio WhatsApp) can be
plugged in later by adjusting the field mapping in `normalize()`.

Expected payload shape (generic / provider-agnostic for Phase 1):
{
    "from": "+1234567890",           # sender phone/WAID
    "to": "+0987654321",             # receiver number
    "message_id": "wamid.xxx",
    "type": "text",
    "text": {"body": "Hello!"},
    "timestamp": "1700000000",       # unix epoch (optional)
    "profile": {"name": "John Doe"} # optional
}
"""
from datetime import datetime, timezone
from typing import Any, Optional

from app.adapters.base import BaseChannelAdapter, ChannelType, UnifiedEvent


class WhatsAppAdapter(BaseChannelAdapter):
    channel = ChannelType.whatsapp

    def normalize(self, tenant_id: str, payload: dict[str, Any]) -> UnifiedEvent:
        sender = payload.get("from", "")
        message_id = payload.get("message_id", "")

        # Extract text from different message types
        message_text: Optional[str] = None
        msg_type = payload.get("type", "text")
        if msg_type == "text":
            text_block = payload.get("text", {})
            message_text = text_block.get("body") if isinstance(text_block, dict) else str(text_block)
        elif msg_type == "interactive":
            # Support button replies etc.
            interactive = payload.get("interactive", {})
            message_text = (
                interactive.get("button_reply", {}).get("title")
                or interactive.get("list_reply", {}).get("title")
            )
        else:
            message_text = payload.get("text", {}).get("body") if isinstance(payload.get("text"), dict) else None

        # Parse timestamp
        ts_raw = payload.get("timestamp")
        if ts_raw:
            try:
                timestamp = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
            except (ValueError, TypeError):
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        # Build metadata
        profile = payload.get("profile", {})
        metadata = {
            "message_id": message_id,
            "message_type": msg_type,
            "to": payload.get("to"),
            "profile_name": profile.get("name") if isinstance(profile, dict) else None,
        }

        return UnifiedEvent(
            tenant_id=tenant_id,
            channel=ChannelType.whatsapp,
            external_user_identifier=sender,
            message_text=message_text,
            timestamp=timestamp,
            raw_payload=payload,
            metadata=metadata,
        )

    def validate_payload(self, payload: dict[str, Any]) -> bool:
        return bool(payload.get("from"))
