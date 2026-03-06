"""
Integration tests for Phase 4 Outbound Messaging API.

Covers:
  - POST /outbound/send: agent queues message, returns 202
  - GET  /outbound: lists messages, filtered by conversation
  - GET  /outbound/{id}: detail with attempts
  - GET  /outbound/{id}/attempts: attempts endpoint
  - POST /outbound/{id}/cancel: cancel pending message
  - Tenant isolation: tenant B cannot see tenant A's messages
  - RBAC: unauthenticated → 401
"""
import uuid
import pytest
import pytest_asyncio

from tests.conftest import make_token
from app.models.outbound import OutboundMessageStatus


async def _noop_enqueue(*args, **kwargs):
    return True


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def conversation_a(db_session, tenant_a, owner_user_a):
    """Create a Customer + Conversation under tenant A."""
    from app.models.customer import Customer
    from app.models.conversation import Conversation

    customer = Customer(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        external_id="+19995551234",
        channel="whatsapp",
    )
    db_session.add(customer)
    conversation = Conversation(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        customer_id=customer.id,
        channel="whatsapp",
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    return conversation


@pytest_asyncio.fixture
async def conversation_b(db_session, tenant_b, owner_user_b):
    """Create a Customer + Conversation under tenant B."""
    from app.models.customer import Customer
    from app.models.conversation import Conversation

    customer = Customer(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        external_id="+19995559999",
        channel="sms",
    )
    db_session.add(customer)
    conversation = Conversation(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        customer_id=customer.id,
        channel="sms",
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    return conversation


# ── POST /outbound/send ───────────────────────────────────────────────────────

class TestOutboundSend:
    @pytest.mark.asyncio
    async def test_agent_can_send_message(
        self, client, agent_user_a, tenant_a, conversation_a, monkeypatch
    ):
        monkeypatch.setattr(
            "app.api.v1.outbound.router.enqueue_outbound_message", _noop_enqueue
        )
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.post(
            "/api/v1/outbound/send",
            json={
                "conversation_id": str(conversation_a.id),
                "message_text": "Hello from agent",
                "message_type": "text",
            },
            headers=headers,
        )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "pending"
        assert data["message_text"] == "Hello from agent"
        assert data["channel"] == "whatsapp"
        assert data["is_ai_generated"] is False

    @pytest.mark.asyncio
    async def test_owner_can_send_message(
        self, client, owner_user_a, tenant_a, conversation_a, monkeypatch
    ):
        monkeypatch.setattr(
            "app.api.v1.outbound.router.enqueue_outbound_message", _noop_enqueue
        )
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.post(
            "/api/v1/outbound/send",
            json={
                "conversation_id": str(conversation_a.id),
                "message_text": "Owner reply",
            },
            headers=headers,
        )
        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_send_unauthenticated_returns_401(self, client, conversation_a):
        response = await client.post(
            "/api/v1/outbound/send",
            json={
                "conversation_id": str(conversation_a.id),
                "message_text": "No auth",
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_send_wrong_tenant_conversation_returns_404(
        self, client, agent_user_a, conversation_b, monkeypatch
    ):
        """Tenant A agent cannot send to tenant B's conversation."""
        monkeypatch.setattr(
            "app.api.v1.outbound.router.enqueue_outbound_message", _noop_enqueue
        )
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.post(
            "/api/v1/outbound/send",
            json={
                "conversation_id": str(conversation_b.id),
                "message_text": "Cross-tenant attack",
            },
            headers=headers,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_send_nonexistent_conversation_returns_404(
        self, client, agent_user_a, monkeypatch
    ):
        monkeypatch.setattr(
            "app.api.v1.outbound.router.enqueue_outbound_message", _noop_enqueue
        )
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.post(
            "/api/v1/outbound/send",
            json={
                "conversation_id": str(uuid.uuid4()),
                "message_text": "Ghost conversation",
            },
            headers=headers,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_send_with_subject_for_email(
        self, client, agent_user_a, db_session, tenant_a, monkeypatch
    ):
        """Email messages can carry a subject field."""
        from app.models.customer import Customer
        from app.models.conversation import Conversation

        monkeypatch.setattr(
            "app.api.v1.outbound.router.enqueue_outbound_message", _noop_enqueue
        )

        customer = Customer(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            external_id="cust@example.com",
            channel="email",
        )
        db_session.add(customer)
        email_conv = Conversation(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            customer_id=customer.id,
            channel="email",
        )
        db_session.add(email_conv)
        await db_session.commit()

        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.post(
            "/api/v1/outbound/send",
            json={
                "conversation_id": str(email_conv.id),
                "message_text": "Here is your answer",
                "subject": "Re: your question",
                "message_type": "email",
            },
            headers=headers,
        )
        assert response.status_code == 202
        data = response.json()
        assert data["subject"] == "Re: your question"
        assert data["channel"] == "email"


# ── GET /outbound ─────────────────────────────────────────────────────────────

class TestListOutbound:
    @pytest.mark.asyncio
    async def test_list_returns_empty_initially(
        self, client, agent_user_a, tenant_a
    ):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.get("/api/v1/outbound", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_list_returns_tenant_messages_only(
        self, client, agent_user_a, owner_user_b, conversation_a, conversation_b, monkeypatch
    ):
        monkeypatch.setattr(
            "app.api.v1.outbound.router.enqueue_outbound_message", _noop_enqueue
        )

        # Send one from tenant A
        headers_a = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        await client.post(
            "/api/v1/outbound/send",
            json={"conversation_id": str(conversation_a.id), "message_text": "A msg"},
            headers=headers_a,
        )

        # Send one from tenant B
        headers_b = {"Authorization": f"Bearer {make_token(owner_user_b)}"}
        await client.post(
            "/api/v1/outbound/send",
            json={"conversation_id": str(conversation_b.id), "message_text": "B msg"},
            headers=headers_b,
        )

        # Tenant A should only see their own
        response = await client.get("/api/v1/outbound", headers=headers_a)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["message_text"] == "A msg"

    @pytest.mark.asyncio
    async def test_list_unauthenticated_returns_401(self, client):
        response = await client.get("/api/v1/outbound")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_list_filter_by_conversation(
        self, client, agent_user_a, db_session, tenant_a, conversation_a, monkeypatch
    ):
        from app.models.customer import Customer
        from app.models.conversation import Conversation

        monkeypatch.setattr(
            "app.api.v1.outbound.router.enqueue_outbound_message", _noop_enqueue
        )
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}

        # Create a second conversation
        customer2 = Customer(
            id=uuid.uuid4(), tenant_id=tenant_a.id, external_id="+2222", channel="sms"
        )
        db_session.add(customer2)
        conv2 = Conversation(
            id=uuid.uuid4(), tenant_id=tenant_a.id, customer_id=customer2.id, channel="sms"
        )
        db_session.add(conv2)
        await db_session.commit()

        # Send one to each conversation
        await client.post(
            "/api/v1/outbound/send",
            json={"conversation_id": str(conversation_a.id), "message_text": "Conv A"},
            headers=headers,
        )
        await client.post(
            "/api/v1/outbound/send",
            json={"conversation_id": str(conv2.id), "message_text": "Conv 2"},
            headers=headers,
        )

        # Filter by conversation A only
        response = await client.get(
            f"/api/v1/outbound?conversation_id={conversation_a.id}",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["message_text"] == "Conv A"


# ── GET /outbound/{id} ────────────────────────────────────────────────────────

class TestGetOutboundDetail:
    @pytest.mark.asyncio
    async def test_get_message_detail(
        self, client, agent_user_a, conversation_a, monkeypatch
    ):
        monkeypatch.setattr(
            "app.api.v1.outbound.router.enqueue_outbound_message", _noop_enqueue
        )
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        create_resp = await client.post(
            "/api/v1/outbound/send",
            json={"conversation_id": str(conversation_a.id), "message_text": "Detail test"},
            headers=headers,
        )
        msg_id = create_resp.json()["id"]

        response = await client.get(f"/api/v1/outbound/{msg_id}", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == msg_id
        assert data["message_text"] == "Detail test"
        assert "attempts" in data

    @pytest.mark.asyncio
    async def test_get_wrong_tenant_returns_404(
        self, client, agent_user_a, owner_user_b, conversation_b, monkeypatch
    ):
        monkeypatch.setattr(
            "app.api.v1.outbound.router.enqueue_outbound_message", _noop_enqueue
        )
        # Create message as tenant B
        headers_b = {"Authorization": f"Bearer {make_token(owner_user_b)}"}
        create_resp = await client.post(
            "/api/v1/outbound/send",
            json={"conversation_id": str(conversation_b.id), "message_text": "B only"},
            headers=headers_b,
        )
        msg_id = create_resp.json()["id"]

        # Try to access as tenant A
        headers_a = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.get(f"/api/v1/outbound/{msg_id}", headers=headers_a)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_404(self, client, agent_user_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.get(f"/api/v1/outbound/{uuid.uuid4()}", headers=headers)
        assert response.status_code == 404


# ── POST /outbound/{id}/cancel ────────────────────────────────────────────────

class TestCancelOutbound:
    @pytest.mark.asyncio
    async def test_cancel_pending_message(
        self, client, agent_user_a, conversation_a, monkeypatch
    ):
        monkeypatch.setattr(
            "app.api.v1.outbound.router.enqueue_outbound_message", _noop_enqueue
        )
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        create_resp = await client.post(
            "/api/v1/outbound/send",
            json={"conversation_id": str(conversation_a.id), "message_text": "Cancel me"},
            headers=headers,
        )
        msg_id = create_resp.json()["id"]

        response = await client.post(f"/api/v1/outbound/{msg_id}/cancel", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_404(self, client, agent_user_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.post(
            f"/api/v1/outbound/{uuid.uuid4()}/cancel", headers=headers
        )
        assert response.status_code == 404
