"""
Integration tests for Phase 2 AI processing.

Tests cover:
- AI job creation from inbound channel flow (when ai_enabled=True)
- AI job NOT created when ai_enabled=False
- GET /ai/jobs endpoint
- GET /ai/jobs/{id} endpoint
- POST /ai/jobs/{id}/retry for failed jobs
- GET /tickets/{id}/ai-result after worker processing
- Ticket status stays pending_agent after AI processing
- Multi-tenant isolation for AI jobs
"""
import uuid
import pytest
import pytest_asyncio
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import TenantConfig
from app.models.ai_job import AIJob, AIJobStatus
from app.models.ai_result import AIResult
from app.models.ticket import Ticket, TicketStatus
from app.worker.tasks import _process_ai_job_inner


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _enable_ai(db: AsyncSession, tenant_id: uuid.UUID, auto_send_mode: str = "off"):
    """Enable AI processing for a tenant."""
    result = await db.execute(
        select(TenantConfig).where(TenantConfig.tenant_id == tenant_id)
    )
    cfg = result.scalar_one_or_none()
    if cfg:
        cfg.ai_enabled = True
        cfg.auto_send_mode = auto_send_mode
    await db.commit()


WHATSAPP_PAYLOAD = {
    "from": "+15551234567",
    "to": "+0000000000",
    "message_id": "wamid.ai-test",
    "type": "text",
    "text": {"body": "Hello, I need help please"},
    "timestamp": "1700000000",
    "profile": {"name": "Test User"},
}


# ── AI job creation from inbound ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_inbound_creates_ai_job_when_ai_enabled(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
):
    """Inbound message creates an AIJob when ai_enabled=True."""
    await _enable_ai(db_session, tenant_a.id)

    resp = await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)
    assert resp.status_code == 202
    data = resp.json()
    assert data["ai_job_id"] is not None

    # Verify AIJob in DB
    result = await db_session.execute(
        select(AIJob).where(AIJob.tenant_id == tenant_a.id)
    )
    jobs = result.scalars().all()
    assert len(jobs) == 1
    assert jobs[0].status == AIJobStatus.pending


@pytest.mark.asyncio
async def test_inbound_no_ai_job_when_ai_disabled(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
):
    """Inbound message does NOT create an AIJob when ai_enabled=False (default)."""
    # ai_enabled defaults to False — no need to change anything
    resp = await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)
    assert resp.status_code == 202
    data = resp.json()
    assert data.get("ai_job_id") is None

    result = await db_session.execute(
        select(AIJob).where(AIJob.tenant_id == tenant_a.id)
    )
    jobs = result.scalars().all()
    assert len(jobs) == 0


@pytest.mark.asyncio
async def test_second_message_creates_second_ai_job(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
):
    """Each inbound message with ai_enabled gets its own AI job."""
    await _enable_ai(db_session, tenant_a.id)

    await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)
    await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)

    result = await db_session.execute(
        select(AIJob).where(AIJob.tenant_id == tenant_a.id)
    )
    jobs = result.scalars().all()
    assert len(jobs) == 2


# ── AI job processing ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_worker_processes_job_and_creates_result(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
):
    """Worker completes job and persists AIResult."""
    await _enable_ai(db_session, tenant_a.id)
    await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)

    job_result = await db_session.execute(select(AIJob).where(AIJob.tenant_id == tenant_a.id))
    job = job_result.scalar_one()

    await _process_ai_job_inner(db_session, str(job.id))

    # Verify result
    res = await db_session.execute(select(AIResult).where(AIResult.ai_job_id == job.id))
    ai_result = res.scalar_one_or_none()
    assert ai_result is not None
    assert ai_result.intent is not None
    assert ai_result.provider_name == "mock"


@pytest.mark.asyncio
async def test_ticket_stays_pending_agent_after_ai(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
):
    """Phase 2: ticket status MUST remain pending_agent regardless of AI outcome."""
    await _enable_ai(db_session, tenant_a.id)
    resp = await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)
    ticket_id = resp.json()["ticket_id"]

    job_result = await db_session.execute(select(AIJob).where(AIJob.tenant_id == tenant_a.id))
    job = job_result.scalar_one()
    await _process_ai_job_inner(db_session, str(job.id))

    ticket_res = await db_session.execute(
        select(Ticket).where(Ticket.id == uuid.UUID(ticket_id))
    )
    ticket = ticket_res.scalar_one()
    assert ticket.status == TicketStatus.pending_agent


# ── AI Jobs API ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_ai_jobs_empty(client: AsyncClient, tenant_a, auth_headers_agent_a):
    resp = await client.get("/api/v1/ai/jobs", headers=auth_headers_agent_a)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_list_ai_jobs_after_inbound(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
    auth_headers_agent_a,
):
    await _enable_ai(db_session, tenant_a.id)
    await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)

    resp = await client.get("/api/v1/ai/jobs", headers=auth_headers_agent_a)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_get_ai_job_by_id(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
    auth_headers_agent_a,
):
    await _enable_ai(db_session, tenant_a.id)
    await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)

    job_res = await db_session.execute(select(AIJob).where(AIJob.tenant_id == tenant_a.id))
    job = job_res.scalar_one()

    resp = await client.get(f"/api/v1/ai/jobs/{job.id}", headers=auth_headers_agent_a)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(job.id)
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_get_ai_job_not_found(client: AsyncClient, auth_headers_agent_a):
    resp = await client.get(f"/api/v1/ai/jobs/{uuid.uuid4()}", headers=auth_headers_agent_a)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_ai_job_cross_tenant_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
    tenant_b,
    auth_headers_owner_b,
):
    """Tenant B cannot see Tenant A's AI jobs."""
    await _enable_ai(db_session, tenant_a.id)
    await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)

    job_res = await db_session.execute(select(AIJob).where(AIJob.tenant_id == tenant_a.id))
    job = job_res.scalar_one()

    # Tenant B tries to access Tenant A's job
    resp = await client.get(f"/api/v1/ai/jobs/{job.id}", headers=auth_headers_owner_b)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ai_job_result_endpoint(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
    auth_headers_agent_a,
):
    await _enable_ai(db_session, tenant_a.id)
    await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)

    job_res = await db_session.execute(select(AIJob).where(AIJob.tenant_id == tenant_a.id))
    job = job_res.scalar_one()
    await _process_ai_job_inner(db_session, str(job.id))

    resp = await client.get(f"/api/v1/ai/jobs/{job.id}/result", headers=auth_headers_agent_a)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ai_job_id"] == str(job.id)
    assert data["intent"] is not None
    assert "confidence" in data
    assert "should_escalate" in data
    assert "safe_to_auto_send" in data


@pytest.mark.asyncio
async def test_ai_job_result_not_found_if_not_completed(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
    auth_headers_agent_a,
):
    """Result endpoint returns 404 if the job hasn't completed yet."""
    await _enable_ai(db_session, tenant_a.id)
    await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)

    job_res = await db_session.execute(select(AIJob).where(AIJob.tenant_id == tenant_a.id))
    job = job_res.scalar_one()

    # Do NOT process the job
    resp = await client.get(f"/api/v1/ai/jobs/{job.id}/result", headers=auth_headers_agent_a)
    assert resp.status_code == 404


# ── Ticket AI result sub-resource ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ticket_ai_result_endpoint(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
    auth_headers_agent_a,
):
    await _enable_ai(db_session, tenant_a.id)
    resp = await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)
    ticket_id = resp.json()["ticket_id"]

    job_res = await db_session.execute(select(AIJob).where(AIJob.tenant_id == tenant_a.id))
    job = job_res.scalar_one()
    await _process_ai_job_inner(db_session, str(job.id))

    resp = await client.get(
        f"/api/v1/tickets/{ticket_id}/ai-result", headers=auth_headers_agent_a
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticket_id"] == ticket_id
    assert data["intent"] is not None


@pytest.mark.asyncio
async def test_ticket_ai_result_404_when_no_result(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
    auth_headers_agent_a,
):
    await _enable_ai(db_session, tenant_a.id)
    resp = await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)
    ticket_id = resp.json()["ticket_id"]

    # Don't process job
    resp = await client.get(
        f"/api/v1/tickets/{ticket_id}/ai-result", headers=auth_headers_agent_a
    )
    assert resp.status_code == 404


# ── Retry endpoint ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_failed_job(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
    auth_headers_agent_a,
):
    await _enable_ai(db_session, tenant_a.id)
    await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)

    job_res = await db_session.execute(select(AIJob).where(AIJob.tenant_id == tenant_a.id))
    job = job_res.scalar_one()
    job.status = AIJobStatus.failed
    job.error_message = "Provider error"
    await db_session.commit()

    resp = await client.post(f"/api/v1/ai/jobs/{job.id}/retry", headers=auth_headers_agent_a)
    assert resp.status_code == 200
    data = resp.json()
    assert data["new_status"] == "pending"


@pytest.mark.asyncio
async def test_retry_non_failed_job_returns_409(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
    auth_headers_agent_a,
):
    await _enable_ai(db_session, tenant_a.id)
    await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)

    job_res = await db_session.execute(select(AIJob).where(AIJob.tenant_id == tenant_a.id))
    job = job_res.scalar_one()
    # Job is still 'pending', not 'failed'

    resp = await client.post(f"/api/v1/ai/jobs/{job.id}/retry", headers=auth_headers_agent_a)
    assert resp.status_code == 409


# ── Unauthenticated ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_jobs_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/ai/jobs")
    assert resp.status_code == 401


# ── List filters ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_ai_jobs_filter_by_status(
    client: AsyncClient,
    db_session: AsyncSession,
    tenant_a,
    auth_headers_agent_a,
):
    await _enable_ai(db_session, tenant_a.id)
    await client.post(f"/api/v1/inbound/whatsapp/{tenant_a.slug}", json=WHATSAPP_PAYLOAD)

    # Filter by pending
    resp = await client.get(
        "/api/v1/ai/jobs?status=pending", headers=auth_headers_agent_a
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    # Filter by completed (none yet)
    resp = await client.get(
        "/api/v1/ai/jobs?status=completed", headers=auth_headers_agent_a
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
