"""
Integration tests for inbound channel endpoints.

Tests that channel payloads are normalized, routed, and stored correctly.
"""
import pytest


@pytest.mark.asyncio
async def test_whatsapp_inbound_creates_entities(client, db_session, tenant_a):
    """POST to WhatsApp inbound creates customer, conversation, ticket, event log."""
    resp = await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json={
        "from": "+1234567890",
        "to": "+0000000000",
        "message_id": "wamid.test1",
        "type": "text",
        "text": {"body": "Hello, I need support"},
        "timestamp": "1700000000",
        "profile": {"name": "Test User"},
    })
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert "customer_id" in data
    assert "conversation_id" in data
    assert "ticket_id" in data
    assert "event_log_id" in data
    assert data["customer_created"] is True
    assert data["conversation_created"] is True
    assert data["ticket_created"] is True


@pytest.mark.asyncio
async def test_whatsapp_second_message_reuses_conversation(client, db_session, tenant_a):
    """Second message from the same sender reuses the existing conversation."""
    payload = {
        "from": "+1999999999",
        "type": "text",
        "text": {"body": "First message"},
        "message_id": "wamid.first",
    }
    r1 = await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=payload)
    assert r1.status_code == 202

    payload2 = {**payload, "text": {"body": "Follow-up"}, "message_id": "wamid.second"}
    r2 = await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=payload2)
    assert r2.status_code == 202

    assert r1.json()["conversation_id"] == r2.json()["conversation_id"]
    assert r2.json()["conversation_created"] is False
    assert r2.json()["ticket_created"] is False


@pytest.mark.asyncio
async def test_webchat_inbound_accepted(client, db_session, tenant_a):
    """WebChat payload is processed and entities are created."""
    resp = await client.post(f"/api/v1/inbound/webchat/{tenant_a.slug}", json={
        "session_id": "sess_abc999",
        "message": "Hi there from the widget",
        "visitor_name": "Widget User",
        "visitor_email": "widget@test.com",
        "page_url": "https://example.com/home",
    })
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["customer_created"] is True


@pytest.mark.asyncio
async def test_sms_inbound_accepted(client, db_session, tenant_a):
    """SMS payload is processed and entities are created."""
    resp = await client.post(f"/api/v1/inbound/sms/{tenant_a.slug}", json={
        "from": "+4444444444",
        "to": "+5555555555",
        "body": "Hello from SMS channel",
        "message_id": "SM_test1",
    })
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["customer_created"] is True


@pytest.mark.asyncio
async def test_inbound_unknown_tenant_returns_404(client):
    """Inbound to unknown tenant slug returns 404."""
    resp = await client.post("/api/v1/inbound/whatsapp/nonexistent-tenant", json={
        "from": "+111", "type": "text", "text": {"body": "hi"}, "message_id": "x"
    })
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_inbound_unknown_channel_returns_404(client, tenant_a):
    """Inbound to unknown channel returns 404."""
    resp = await client.post(f"/api/v1/inbound/telegram/{tenant_a.slug}", json={"from": "+111"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_whatsapp_invalid_payload_returns_422(client, tenant_a):
    """WhatsApp payload without 'from' field is rejected."""
    resp = await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json={
        "type": "text",
        "text": {"body": "no sender"},
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_inbound_channels_are_tenant_isolated(client, db_session, tenant_a, tenant_b):
    """Messages sent to different tenant slugs produce isolated customers."""
    payload_a = {"from": "+7777777777", "type": "text", "text": {"body": "For A"}, "message_id": "m1"}
    payload_b = {"from": "+7777777777", "type": "text", "text": {"body": "For B"}, "message_id": "m2"}

    r_a = await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=payload_a)
    r_b = await client.post(f"/api/v1/inbound/whatsapp/{tenant_b.slug}", json=payload_b)

    assert r_a.status_code == 202
    assert r_b.status_code == 202

    # Same phone number produces different customer records (different tenants)
    assert r_a.json()["customer_id"] != r_b.json()["customer_id"]
    assert r_a.json()["conversation_id"] != r_b.json()["conversation_id"]
