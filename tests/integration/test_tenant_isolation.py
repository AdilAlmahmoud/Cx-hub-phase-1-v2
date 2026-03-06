"""
Integration tests for multi-tenant isolation.

These tests verify that:
1. Tenant A users cannot see Tenant B's data
2. Resources are strictly scoped to the authenticated user's tenant
3. Cross-tenant access attempts return 404 (not 403, to avoid enumeration)
"""
import uuid
import pytest
from sqlalchemy import select

from app.models.customer import Customer
from app.models.conversation import Conversation
from app.models.ticket import Ticket
from app.models.user import User, UserRole
from app.core.security import hash_password


# ── Customer isolation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_customer_list_only_returns_own_tenant(
    client, db_session, tenant_a, tenant_b, auth_headers_owner_a, auth_headers_owner_b
):
    """Tenant A and Tenant B customers are isolated."""
    # Create customer for tenant A
    cust_a = Customer(
        id=uuid.uuid4(), tenant_id=tenant_a.id,
        external_id="+11111", channel="sms", name="Customer A"
    )
    # Create customer for tenant B
    cust_b = Customer(
        id=uuid.uuid4(), tenant_id=tenant_b.id,
        external_id="+22222", channel="sms", name="Customer B"
    )
    db_session.add_all([cust_a, cust_b])
    await db_session.commit()

    # Tenant A owner sees only Tenant A customers
    resp_a = await client.get("/api/v1/customers", headers=auth_headers_owner_a)
    assert resp_a.status_code == 200
    items_a = resp_a.json()["items"]
    ids_a = [i["id"] for i in items_a]
    assert str(cust_a.id) in ids_a
    assert str(cust_b.id) not in ids_a

    # Tenant B owner sees only Tenant B customers
    resp_b = await client.get("/api/v1/customers", headers=auth_headers_owner_b)
    assert resp_b.status_code == 200
    items_b = resp_b.json()["items"]
    ids_b = [i["id"] for i in items_b]
    assert str(cust_b.id) in ids_b
    assert str(cust_a.id) not in ids_b


@pytest.mark.asyncio
async def test_customer_get_cross_tenant_returns_404(
    client, db_session, tenant_a, tenant_b, auth_headers_owner_b
):
    """Tenant B cannot access Tenant A's customer by ID."""
    cust_a = Customer(
        id=uuid.uuid4(), tenant_id=tenant_a.id,
        external_id="+33333", channel="whatsapp"
    )
    db_session.add(cust_a)
    await db_session.commit()

    resp = await client.get(f"/api/v1/customers/{cust_a.id}", headers=auth_headers_owner_b)
    assert resp.status_code == 404


# ── Conversation isolation ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_conversation_list_isolated_by_tenant(
    client, db_session, tenant_a, tenant_b, auth_headers_agent_a, auth_headers_owner_b
):
    """Conversations belong to their tenant and are invisible to others."""
    cust_a = Customer(id=uuid.uuid4(), tenant_id=tenant_a.id, external_id="wa_1", channel="whatsapp")
    cust_b = Customer(id=uuid.uuid4(), tenant_id=tenant_b.id, external_id="wa_2", channel="whatsapp")
    db_session.add_all([cust_a, cust_b])
    await db_session.flush()

    conv_a = Conversation(id=uuid.uuid4(), tenant_id=tenant_a.id, customer_id=cust_a.id, channel="whatsapp")
    conv_b = Conversation(id=uuid.uuid4(), tenant_id=tenant_b.id, customer_id=cust_b.id, channel="whatsapp")
    db_session.add_all([conv_a, conv_b])
    await db_session.commit()

    # Agent of tenant A sees only tenant A's conversation
    resp_a = await client.get("/api/v1/conversations", headers=auth_headers_agent_a)
    assert resp_a.status_code == 200
    ids_a = [i["id"] for i in resp_a.json()["items"]]
    assert str(conv_a.id) in ids_a
    assert str(conv_b.id) not in ids_a

    # Owner of tenant B sees only tenant B's conversation
    resp_b = await client.get("/api/v1/conversations", headers=auth_headers_owner_b)
    assert resp_b.status_code == 200
    ids_b = [i["id"] for i in resp_b.json()["items"]]
    assert str(conv_b.id) in ids_b
    assert str(conv_a.id) not in ids_b


@pytest.mark.asyncio
async def test_conversation_get_cross_tenant_returns_404(
    client, db_session, tenant_a, tenant_b, auth_headers_owner_b
):
    """Tenant B cannot access Tenant A's conversation by ID."""
    cust_a = Customer(id=uuid.uuid4(), tenant_id=tenant_a.id, external_id="wa_x", channel="whatsapp")
    db_session.add(cust_a)
    await db_session.flush()
    conv_a = Conversation(id=uuid.uuid4(), tenant_id=tenant_a.id, customer_id=cust_a.id, channel="whatsapp")
    db_session.add(conv_a)
    await db_session.commit()

    resp = await client.get(f"/api/v1/conversations/{conv_a.id}", headers=auth_headers_owner_b)
    assert resp.status_code == 404


# ── Ticket isolation ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ticket_list_isolated_by_tenant(
    client, db_session, tenant_a, tenant_b, auth_headers_agent_a, auth_headers_owner_b
):
    """Tickets for different tenants are not visible cross-tenant."""
    cust_a = Customer(id=uuid.uuid4(), tenant_id=tenant_a.id, external_id="sms_t1", channel="sms")
    cust_b = Customer(id=uuid.uuid4(), tenant_id=tenant_b.id, external_id="sms_t2", channel="sms")
    db_session.add_all([cust_a, cust_b])
    await db_session.flush()

    conv_a = Conversation(id=uuid.uuid4(), tenant_id=tenant_a.id, customer_id=cust_a.id, channel="sms")
    conv_b = Conversation(id=uuid.uuid4(), tenant_id=tenant_b.id, customer_id=cust_b.id, channel="sms")
    db_session.add_all([conv_a, conv_b])
    await db_session.flush()

    ticket_a = Ticket(
        id=uuid.uuid4(), tenant_id=tenant_a.id,
        conversation_id=conv_a.id, ticket_number=1
    )
    ticket_b = Ticket(
        id=uuid.uuid4(), tenant_id=tenant_b.id,
        conversation_id=conv_b.id, ticket_number=1
    )
    db_session.add_all([ticket_a, ticket_b])
    await db_session.commit()

    resp_a = await client.get("/api/v1/tickets", headers=auth_headers_agent_a)
    assert resp_a.status_code == 200
    ids_a = [i["id"] for i in resp_a.json()["items"]]
    assert str(ticket_a.id) in ids_a
    assert str(ticket_b.id) not in ids_a

    resp_b = await client.get("/api/v1/tickets", headers=auth_headers_owner_b)
    assert resp_b.status_code == 200
    ids_b = [i["id"] for i in resp_b.json()["items"]]
    assert str(ticket_b.id) in ids_b
    assert str(ticket_a.id) not in ids_b


@pytest.mark.asyncio
async def test_ticket_get_cross_tenant_returns_404(
    client, db_session, tenant_a, tenant_b, auth_headers_owner_b
):
    """Tenant B cannot access Tenant A's ticket by ID."""
    cust_a = Customer(id=uuid.uuid4(), tenant_id=tenant_a.id, external_id="sms_c", channel="sms")
    db_session.add(cust_a)
    await db_session.flush()
    conv_a = Conversation(id=uuid.uuid4(), tenant_id=tenant_a.id, customer_id=cust_a.id, channel="sms")
    db_session.add(conv_a)
    await db_session.flush()
    ticket_a = Ticket(id=uuid.uuid4(), tenant_id=tenant_a.id, conversation_id=conv_a.id, ticket_number=99)
    db_session.add(ticket_a)
    await db_session.commit()

    resp = await client.get(f"/api/v1/tickets/{ticket_a.id}", headers=auth_headers_owner_b)
    assert resp.status_code == 404


# ── User isolation ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_list_isolated_by_tenant(
    client, db_session, tenant_a, tenant_b, owner_user_a, owner_user_b,
    auth_headers_owner_a, auth_headers_owner_b
):
    """User listings are scoped to the authenticated user's tenant."""
    resp_a = await client.get("/api/v1/users", headers=auth_headers_owner_a)
    assert resp_a.status_code == 200
    ids_a = [i["id"] for i in resp_a.json()["items"]]
    assert str(owner_user_a.id) in ids_a
    assert str(owner_user_b.id) not in ids_a

    resp_b = await client.get("/api/v1/users", headers=auth_headers_owner_b)
    assert resp_b.status_code == 200
    ids_b = [i["id"] for i in resp_b.json()["items"]]
    assert str(owner_user_b.id) in ids_b
    assert str(owner_user_a.id) not in ids_b


# ── RBAC tests ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_cannot_create_user(client, tenant_a, agent_user_a, auth_headers_agent_a):
    """Agents don't have permission to create users (owner-only)."""
    resp = await client.post("/api/v1/users", headers=auth_headers_agent_a, json={
        "email": "new@tenant-a.com",
        "full_name": "New User",
        "role": "agent",
        "password": "Secure123!",
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(client):
    """Requests without a token are rejected with 401."""
    for endpoint in ["/api/v1/customers", "/api/v1/conversations", "/api/v1/tickets"]:
        resp = await client.get(endpoint)
        assert resp.status_code == 401, f"Expected 401 for {endpoint}, got {resp.status_code}"
