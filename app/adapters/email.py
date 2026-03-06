"""
Email Channel Adapter.

Normalises an inbound email payload into a UnifiedEvent.
Real provider integration (e.g. SendGrid Inbound Parse, Mailgun Route,
AWS SES SNS notification) can be plugged in later by adjusting the field
mapping in `normalize()`.

Expected payload shape (provider-agnostic):
{
    "from": "sender@example.com",
    "to": "support@tenant.com",
    "subject": "Help with my order",
    "body": "Hi, I need help ...",
    "message_id": "<unique-id@mail.example.com>",
    "in_reply_to": "<previous-id@mail.example.com>",  # optional
    "thread_id": "abc123",                             # optional
    "timestamp": "2026-03-06T12:00:00Z",               # ISO-8601 or unix epoch
    "attachments": []                                  # optional, ignored for now
}
"""
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any, Optional

from app.adapters.base import BaseChannelAdapter, ChannelType, UnifiedEvent


class EmailAdapter(BaseChannelAdapter):
    channel = ChannelType.email

    def normalize(self, tenant_id: str, payload: dict[str, Any]) -> UnifiedEvent:
        # Sender — use RFC 2822 parseaddr so "Name <addr>" works too
        raw_from = payload.get("from", "") or ""
        _, sender_email = parseaddr(raw_from)
        if not sender_email:
            sender_email = raw_from  # fallback: use as-is

        subject: str = (payload.get("subject") or "").strip()

        # Body: prefer plain text; fall back to html_body stripped of tags
        body: Optional[str] = payload.get("body") or payload.get("text") or payload.get("html_body")
        if body:
            body = body.strip() or None

        message_id: str = payload.get("message_id", "") or ""

        # Parse timestamp
        ts_raw = payload.get("timestamp")
        if ts_raw:
            try:
                if isinstance(ts_raw, (int, float)):
                    timestamp = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
                else:
                    timestamp = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        metadata = {
            "message_id": message_id,
            "subject": subject,
            "from_raw": raw_from,
            "to": payload.get("to"),
            "in_reply_to": payload.get("in_reply_to"),
            "thread_id": payload.get("thread_id"),
            "has_attachments": bool(payload.get("attachments")),
        }

        return UnifiedEvent(
            tenant_id=tenant_id,
            channel=ChannelType.email,
            external_user_identifier=sender_email,
            message_text=body or subject or "(no content)",
            timestamp=timestamp,
            raw_payload=payload,
            metadata=metadata,
        )

    def validate_payload(self, payload: dict[str, Any]) -> bool:
        return bool(payload.get("from"))
