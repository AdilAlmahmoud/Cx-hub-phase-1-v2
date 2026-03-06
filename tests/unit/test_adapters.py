"""
Unit tests for channel adapters.

Tests:
- WhatsApp, WebChat, SMS adapters produce a valid UnifiedEvent
- All required UnifiedEvent fields are populated
- timestamp parsing from various formats
- Edge cases (missing optional fields, unknown message types)
"""
from datetime import datetime, timezone

import pytest

from app.adapters.base import ChannelType, UnifiedEvent
from app.adapters.whatsapp import WhatsAppAdapter
from app.adapters.webchat import WebChatAdapter
from app.adapters.sms import SMSAdapter

TENANT_ID = "00000000-0000-0000-0000-000000000001"


# ── WhatsApp Adapter ──────────────────────────────────────────────────────────

class TestWhatsAppAdapter:
    def setup_method(self):
        self.adapter = WhatsAppAdapter()

    def _payload(self, **kwargs):
        base = {
            "from": "+1234567890",
            "to": "+0987654321",
            "message_id": "wamid.abc123",
            "type": "text",
            "text": {"body": "Hello from WhatsApp"},
            "timestamp": "1700000000",
            "profile": {"name": "John Doe"},
        }
        base.update(kwargs)
        return base

    def test_normalizes_to_unified_event(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert isinstance(event, UnifiedEvent)

    def test_channel_is_whatsapp(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert event.channel == ChannelType.whatsapp.value

    def test_external_user_identifier_is_sender(self):
        event = self.adapter.normalize(TENANT_ID, self._payload(**{"from": "+1111111111"}))
        assert event.external_user_identifier == "+1111111111"

    def test_message_text_extracted(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert event.message_text == "Hello from WhatsApp"

    def test_tenant_id_preserved(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert event.tenant_id == TENANT_ID

    def test_timestamp_parsed_from_unix(self):
        event = self.adapter.normalize(TENANT_ID, self._payload(timestamp="1700000000"))
        assert event.timestamp == datetime.fromtimestamp(1700000000, tz=timezone.utc)

    def test_timestamp_defaults_when_missing(self):
        payload = self._payload()
        del payload["timestamp"]
        event = self.adapter.normalize(TENANT_ID, payload)
        assert event.timestamp is not None
        assert event.timestamp.tzinfo is not None

    def test_metadata_contains_message_id(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert event.metadata["message_id"] == "wamid.abc123"

    def test_metadata_contains_profile_name(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert event.metadata["profile_name"] == "John Doe"

    def test_raw_payload_preserved(self):
        payload = self._payload()
        event = self.adapter.normalize(TENANT_ID, payload)
        assert event.raw_payload == payload

    def test_interactive_message_type(self):
        payload = self._payload(
            type="interactive",
            interactive={"button_reply": {"title": "Yes please"}},
        )
        del payload["text"]
        event = self.adapter.normalize(TENANT_ID, payload)
        assert event.message_text == "Yes please"

    def test_validate_payload_true_with_from(self):
        assert self.adapter.validate_payload(self._payload()) is True

    def test_validate_payload_false_without_from(self):
        payload = self._payload()
        del payload["from"]
        assert self.adapter.validate_payload(payload) is False

    def test_event_id_is_unique(self):
        e1 = self.adapter.normalize(TENANT_ID, self._payload())
        e2 = self.adapter.normalize(TENANT_ID, self._payload())
        assert e1.event_id != e2.event_id


# ── WebChat Adapter ───────────────────────────────────────────────────────────

class TestWebChatAdapter:
    def setup_method(self):
        self.adapter = WebChatAdapter()

    def _payload(self, **kwargs):
        base = {
            "session_id": "sess_abc123",
            "message": "Hello from widget",
            "timestamp": "2024-01-15T10:30:00Z",
            "visitor_name": "Jane Doe",
            "visitor_email": "jane@example.com",
            "page_url": "https://client.com/pricing",
        }
        base.update(kwargs)
        return base

    def test_normalizes_to_unified_event(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert isinstance(event, UnifiedEvent)

    def test_channel_is_webchat(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert event.channel == ChannelType.webchat.value

    def test_session_id_is_external_identifier(self):
        event = self.adapter.normalize(TENANT_ID, self._payload(session_id="sess_xyz"))
        assert event.external_user_identifier == "sess_xyz"

    def test_message_text_extracted(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert event.message_text == "Hello from widget"

    def test_text_field_fallback(self):
        payload = self._payload()
        del payload["message"]
        payload["text"] = "Fallback text"
        event = self.adapter.normalize(TENANT_ID, payload)
        assert event.message_text == "Fallback text"

    def test_iso_timestamp_parsed(self):
        event = self.adapter.normalize(TENANT_ID, self._payload(timestamp="2024-01-15T10:30:00Z"))
        assert event.timestamp.year == 2024
        assert event.timestamp.month == 1
        assert event.timestamp.tzinfo is not None

    def test_unix_timestamp_parsed(self):
        event = self.adapter.normalize(TENANT_ID, self._payload(timestamp=1700000000))
        assert event.timestamp == datetime.fromtimestamp(1700000000, tz=timezone.utc)

    def test_timestamp_defaults_when_missing(self):
        payload = self._payload()
        del payload["timestamp"]
        event = self.adapter.normalize(TENANT_ID, payload)
        assert event.timestamp is not None

    def test_metadata_contains_visitor_info(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert event.metadata["visitor_name"] == "Jane Doe"
        assert event.metadata["visitor_email"] == "jane@example.com"
        assert event.metadata["page_url"] == "https://client.com/pricing"

    def test_validate_payload_true_with_session_id(self):
        assert self.adapter.validate_payload(self._payload()) is True

    def test_validate_payload_false_without_session_id(self):
        payload = self._payload()
        del payload["session_id"]
        assert self.adapter.validate_payload(payload) is False


# ── SMS Adapter ───────────────────────────────────────────────────────────────

class TestSMSAdapter:
    def setup_method(self):
        self.adapter = SMSAdapter()

    def _payload(self, **kwargs):
        base = {
            "from": "+1234567890",
            "to": "+0987654321",
            "body": "Hello from SMS",
            "message_id": "SM_abc123",
            "timestamp": "2024-01-15T10:30:00Z",
        }
        base.update(kwargs)
        return base

    def test_normalizes_to_unified_event(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert isinstance(event, UnifiedEvent)

    def test_channel_is_sms(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert event.channel == ChannelType.sms.value

    def test_from_is_external_identifier(self):
        event = self.adapter.normalize(TENANT_ID, self._payload(**{"from": "+5555555555"}))
        assert event.external_user_identifier == "+5555555555"

    def test_body_extracted_as_message(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert event.message_text == "Hello from SMS"

    def test_text_field_fallback(self):
        payload = self._payload()
        del payload["body"]
        payload["text"] = "Text fallback"
        event = self.adapter.normalize(TENANT_ID, payload)
        assert event.message_text == "Text fallback"

    def test_message_field_fallback(self):
        payload = self._payload()
        del payload["body"]
        payload["message"] = "Message fallback"
        event = self.adapter.normalize(TENANT_ID, payload)
        assert event.message_text == "Message fallback"

    def test_iso_timestamp_parsed(self):
        event = self.adapter.normalize(TENANT_ID, self._payload(timestamp="2024-06-01T00:00:00Z"))
        assert event.timestamp.year == 2024
        assert event.timestamp.month == 6

    def test_unix_epoch_timestamp(self):
        event = self.adapter.normalize(TENANT_ID, self._payload(timestamp=1700000000))
        assert event.timestamp == datetime.fromtimestamp(1700000000, tz=timezone.utc)

    def test_metadata_contains_message_id(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert event.metadata["message_id"] == "SM_abc123"

    def test_metadata_contains_to(self):
        event = self.adapter.normalize(TENANT_ID, self._payload())
        assert event.metadata["to"] == "+0987654321"

    def test_validate_payload_true(self):
        assert self.adapter.validate_payload(self._payload()) is True

    def test_validate_payload_false_without_from(self):
        payload = self._payload()
        del payload["from"]
        assert self.adapter.validate_payload(payload) is False


# ── Cross-adapter normalization contract ──────────────────────────────────────

class TestUnifiedEventContract:
    """All adapters must produce a UnifiedEvent with the required fields."""

    @pytest.mark.parametrize("adapter,payload", [
        (
            WhatsAppAdapter(),
            {"from": "+111", "type": "text", "text": {"body": "hi"}, "message_id": "x"},
        ),
        (
            WebChatAdapter(),
            {"session_id": "s1", "message": "hi"},
        ),
        (
            SMSAdapter(),
            {"from": "+111", "body": "hi"},
        ),
    ])
    def test_required_fields_present(self, adapter, payload):
        event = adapter.normalize(TENANT_ID, payload)
        assert event.tenant_id == TENANT_ID
        assert event.channel is not None
        assert event.external_user_identifier is not None
        assert event.timestamp is not None
        assert event.event_id is not None

    @pytest.mark.parametrize("adapter,payload", [
        (WhatsAppAdapter(), {"from": "+111", "type": "text", "text": {"body": "hi"}, "message_id": "x"}),
        (WebChatAdapter(), {"session_id": "s1", "message": "hi"}),
        (SMSAdapter(), {"from": "+111", "body": "hi"}),
    ])
    def test_channel_values_are_valid(self, adapter, payload):
        event = adapter.normalize(TENANT_ID, payload)
        valid_channels = {ct.value for ct in ChannelType}
        assert event.channel in valid_channels
