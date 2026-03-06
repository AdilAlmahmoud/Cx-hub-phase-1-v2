"""
SMS Channel Adapter.

Accepts a generic HTTP payload representing an inbound SMS message.
Real provider integration (e.g. Twilio, Vonage/Nexmo, AWS SNS) can be
plugged in later by adjusting field mapping in `normalize()`.

Expected payload shape (generic / provider-agnostic for Phase 1):
{
    "from": "+1234567890",    # sender phone number (E.164)
    "to": "+0987654321",      # destination number
    "body": "Hello!",         # SMS body text
    "message_id": "SM_xxx",   # provider message ID (optional)
    "timestamp": "2024-01-01T12:00:00Z"  # ISO 8601 or unix epoch (optional)
}
"""
from datetime import datetime, timezone
from typing import Any

from app.adapters.base import BaseChannelAdapter, ChannelType, UnifiedEvent


class SMSAdapter(BaseChannelAdapter):
    channel = ChannelType.sms

    def normalize(self, tenant_id: str, payload: dict[str, Any]) -> UnifiedEvent:
        sender = payload.get("from", "")
        message_text = payload.get("body") or payload.get("text") or payload.get("message")

        # Parse timestamp (ISO 8601 or unix epoch)
        ts_raw = payload.get("timestamp")
        if ts_raw:
            try:
                if isinstance(ts_raw, str):
                    timestamp = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                elif isinstance(ts_raw, (int, float)):
                    timestamp = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
                else:
                    timestamp = datetime.now(timezone.utc)
            except (ValueError, TypeError):
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        metadata = {
            "message_id": payload.get("message_id"),
            "to": payload.get("to"),
            "num_segments": payload.get("num_segments"),
            "provider": payload.get("provider"),
        }

        return UnifiedEvent(
            tenant_id=tenant_id,
            channel=ChannelType.sms,
            external_user_identifier=sender,
            message_text=message_text,
            timestamp=timestamp,
            raw_payload=payload,
            metadata=metadata,
        )

    def validate_payload(self, payload: dict[str, Any]) -> bool:
        return bool(payload.get("from"))
