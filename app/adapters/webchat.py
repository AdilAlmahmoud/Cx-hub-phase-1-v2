"""
Web Chat Channel Adapter.

Accepts HTTP payloads from the embedded web chat widget.
The widget sends messages directly to this endpoint.

Expected payload shape:
{
    "session_id": "sess_abc123",     # browser/visitor session identifier
    "message": "Hello, I need help", # message text
    "timestamp": "2024-01-01T12:00:00Z",  # ISO 8601 (optional)
    "visitor_name": "Jane Doe",       # optional
    "visitor_email": "jane@example.com", # optional
    "page_url": "https://client.com/pricing", # page visitor was on
    "metadata": {}                    # additional custom data
}
"""
from datetime import datetime, timezone
from typing import Any

from app.adapters.base import BaseChannelAdapter, ChannelType, UnifiedEvent


class WebChatAdapter(BaseChannelAdapter):
    channel = ChannelType.webchat

    def normalize(self, tenant_id: str, payload: dict[str, Any]) -> UnifiedEvent:
        session_id = payload.get("session_id", "")
        message_text = payload.get("message") or payload.get("text")

        # Parse timestamp
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
            "visitor_name": payload.get("visitor_name"),
            "visitor_email": payload.get("visitor_email"),
            "page_url": payload.get("page_url"),
            "user_agent": payload.get("user_agent"),
            **(payload.get("metadata") or {}),
        }

        return UnifiedEvent(
            tenant_id=tenant_id,
            channel=ChannelType.webchat,
            external_user_identifier=session_id,
            message_text=message_text,
            timestamp=timestamp,
            raw_payload=payload,
            metadata=metadata,
        )

    def validate_payload(self, payload: dict[str, Any]) -> bool:
        return bool(payload.get("session_id"))
