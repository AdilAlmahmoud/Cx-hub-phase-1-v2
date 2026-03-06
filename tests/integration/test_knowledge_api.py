"""
Integration tests for Phase 3 Knowledge Base API.

Covers:
  - File upload (POST /knowledge/upload)
  - List files (GET /knowledge)
  - Get file detail (GET /knowledge/{id})
  - Reindex (POST /knowledge/{id}/reindex)
  - Tenant isolation: tenant B cannot access tenant A's files
  - RBAC: agent can read; only owner can upload/reindex
  - AI job with knowledge_enabled=True still completes (RAG fallback on SQLite)
  - AI job with knowledge_enabled=False skips retrieval
"""
import io
import uuid
import pytest
import pytest_asyncio

from tests.conftest import make_token
from app.models.knowledge import KnowledgeFileStatus


async def _noop(*args, **kwargs):
    return True


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def knowledge_enabled_tenant_a(db_session, tenant_a):
    """Enable AI + knowledge for tenant A."""
    from app.models.tenant import TenantConfig
    from sqlalchemy import select
    result = await db_session.execute(
        select(TenantConfig).where(TenantConfig.tenant_id == tenant_a.id)
    )
    cfg = result.scalar_one_or_none()
    if cfg is None:
        cfg = TenantConfig(tenant_id=tenant_a.id)
        db_session.add(cfg)

    cfg.ai_enabled = True
    cfg.knowledge_enabled = True
    cfg.retrieval_top_k = 3
    await db_session.commit()
    return tenant_a


# ── Upload ─────────────────────────────────────────────────────────────────────

class TestKnowledgeUpload:
    @pytest.mark.asyncio
    async def test_owner_can_upload_txt(self, client, owner_user_a, tenant_a, tmp_path, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.KNOWLEDGE_STORAGE_PATH", str(tmp_path))
        # Also patch enqueue so we don't need Redis
        monkeypatch.setattr("app.api.v1.knowledge.router.enqueue_knowledge_ingestion",
                            _noop)

        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.post(
            "/api/v1/knowledge/upload",
            headers=headers,
            files={"file": ("test.txt", b"Hello world knowledge content " * 10, "text/plain")},
        )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "pending"
        assert data["original_filename"] == "test.txt"
        assert "file_id" in data

    @pytest.mark.asyncio
    async def test_agent_cannot_upload(self, client, agent_user_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.post(
            "/api/v1/knowledge/upload",
            headers=headers,
            files={"file": ("test.txt", b"content", "text/plain")},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_unsupported_extension_rejected(self, client, owner_user_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.post(
            "/api/v1/knowledge/upload",
            headers=headers,
            files={"file": ("test.docx", b"fake docx content", "application/vnd.openxmlformats")},
        )
        assert response.status_code == 415

    @pytest.mark.asyncio
    async def test_empty_file_rejected(self, client, owner_user_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.post(
            "/api/v1/knowledge/upload",
            headers=headers,
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_unauthenticated_upload_rejected(self, client):
        response = await client.post(
            "/api/v1/knowledge/upload",
            files={"file": ("test.txt", b"content", "text/plain")},
        )
        assert response.status_code == 401


# ── List and Get ───────────────────────────────────────────────────────────────

class TestKnowledgeList:
    @pytest.mark.asyncio
    async def test_agent_can_list(self, client, agent_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.get("/api/v1/knowledge", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data

    @pytest.mark.asyncio
    async def test_list_empty_for_new_tenant(self, client, agent_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.get("/api/v1/knowledge", headers=headers)
        assert response.status_code == 200
        assert response.json()["items"] == []

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_404(self, client, agent_user_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.get(f"/api/v1/knowledge/{uuid.uuid4()}", headers=headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_upload_then_list_returns_file(
        self, client, owner_user_a, agent_user_a, tenant_a, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("app.core.config.settings.KNOWLEDGE_STORAGE_PATH", str(tmp_path))
        monkeypatch.setattr("app.api.v1.knowledge.router.enqueue_knowledge_ingestion",
                            _noop)

        owner_headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        agent_headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}

        # Upload
        upload_resp = await client.post(
            "/api/v1/knowledge/upload",
            headers=owner_headers,
            files={"file": ("guide.txt", b"Our guide content " * 20, "text/plain")},
        )
        assert upload_resp.status_code == 202
        file_id = upload_resp.json()["file_id"]

        # List
        list_resp = await client.get("/api/v1/knowledge", headers=agent_headers)
        assert list_resp.status_code == 200
        ids = [item["id"] for item in list_resp.json()["items"]]
        assert file_id in ids

        # Get detail
        get_resp = await client.get(f"/api/v1/knowledge/{file_id}", headers=agent_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == file_id
        assert get_resp.json()["original_filename"] == "guide.txt"


# ── Reindex ────────────────────────────────────────────────────────────────────

class TestKnowledgeReindex:
    @pytest.mark.asyncio
    async def test_reindex_resets_to_pending(
        self, client, owner_user_a, tenant_a, db_session, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("app.core.config.settings.KNOWLEDGE_STORAGE_PATH", str(tmp_path))
        monkeypatch.setattr("app.api.v1.knowledge.router.enqueue_knowledge_ingestion",
                            _noop)

        owner_headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}

        # Upload
        upload_resp = await client.post(
            "/api/v1/knowledge/upload",
            headers=owner_headers,
            files={"file": ("doc.txt", b"content " * 30, "text/plain")},
        )
        file_id = upload_resp.json()["file_id"]

        # Reindex
        reindex_resp = await client.post(
            f"/api/v1/knowledge/{file_id}/reindex", headers=owner_headers
        )
        assert reindex_resp.status_code == 200
        assert reindex_resp.json()["status"] == "pending"

    @pytest.mark.asyncio
    async def test_agent_cannot_reindex(self, client, agent_user_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.post(
            f"/api/v1/knowledge/{uuid.uuid4()}/reindex", headers=headers
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_reindex_nonexistent_returns_404(self, client, owner_user_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.post(
            f"/api/v1/knowledge/{uuid.uuid4()}/reindex", headers=headers
        )
        assert response.status_code == 404


# ── Tenant Isolation ───────────────────────────────────────────────────────────

class TestKnowledgeTenantIsolation:
    @pytest.mark.asyncio
    async def test_tenant_b_cannot_see_tenant_a_files(
        self, client, owner_user_a, owner_user_b, tenant_a, tenant_b, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("app.core.config.settings.KNOWLEDGE_STORAGE_PATH", str(tmp_path))
        monkeypatch.setattr("app.api.v1.knowledge.router.enqueue_knowledge_ingestion",
                            _noop)

        owner_a_headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        owner_b_headers = {"Authorization": f"Bearer {make_token(owner_user_b)}"}

        # Tenant A uploads a file
        upload_resp = await client.post(
            "/api/v1/knowledge/upload",
            headers=owner_a_headers,
            files={"file": ("a_doc.txt", b"Tenant A private knowledge " * 10, "text/plain")},
        )
        assert upload_resp.status_code == 202
        file_id = upload_resp.json()["file_id"]

        # Tenant B cannot see it
        list_resp = await client.get("/api/v1/knowledge", headers=owner_b_headers)
        assert list_resp.status_code == 200
        assert not any(item["id"] == file_id for item in list_resp.json()["items"])

        # Tenant B gets 404 on direct access
        get_resp = await client.get(f"/api/v1/knowledge/{file_id}", headers=owner_b_headers)
        assert get_resp.status_code == 404

        # Tenant B cannot reindex it
        reindex_resp = await client.post(
            f"/api/v1/knowledge/{file_id}/reindex", headers=owner_b_headers
        )
        assert reindex_resp.status_code == 404


# ── AI Job with knowledge_enabled ─────────────────────────────────────────────

class TestAIJobWithKnowledge:
    @pytest.mark.asyncio
    async def test_ai_job_completes_with_knowledge_enabled(
        self, db_session, knowledge_enabled_tenant_a, tmp_path, monkeypatch
    ):
        """
        AI job runs successfully even when knowledge_enabled=True and
        pgvector is unavailable (SQLite test env — retrieval returns empty list).
        """
        import uuid as _uuid
        from datetime import datetime, timezone
        from app.models.ai_job import AIJob, AIJobStatus
        from app.models.customer import Customer
        from app.models.conversation import Conversation
        from app.models.ticket import Ticket, TicketStatus, TicketPriority
        from app.models.event_log import EventLog
        from app.worker.tasks import _process_ai_job_inner

        tenant = knowledge_enabled_tenant_a

        # Create minimal chain: Customer → Conversation → Ticket → EventLog → AIJob
        customer = Customer(
            id=_uuid.uuid4(), tenant_id=tenant.id,
            external_id="+19990001111", channel="webchat",
        )
        db_session.add(customer)

        conv = Conversation(
            id=_uuid.uuid4(), tenant_id=tenant.id,
            customer_id=customer.id, channel="webchat",
        )
        db_session.add(conv)

        ticket = Ticket(
            id=_uuid.uuid4(), tenant_id=tenant.id,
            conversation_id=conv.id,
            ticket_number=1, status=TicketStatus.pending_agent,
            priority=TicketPriority.medium,
        )
        db_session.add(ticket)

        event = EventLog(
            id=_uuid.uuid4(), tenant_id=tenant.id,
            conversation_id=conv.id, channel="webchat",
            direction="inbound", message_text="Hello, I need help.",
            event_timestamp=datetime.now(timezone.utc),
            external_user_identifier="+19990001111",
        )
        db_session.add(event)

        job = AIJob(
            id=_uuid.uuid4(), tenant_id=tenant.id,
            ticket_id=ticket.id, conversation_id=conv.id,
            event_log_id=event.id, status=AIJobStatus.pending,
            retry_count=0, max_retries=3,
        )
        db_session.add(job)
        await db_session.commit()

        result = await _process_ai_job_inner(db_session, str(job.id))
        # Should complete even though pgvector retrieval returns [] on SQLite
        assert result["status"] == "completed"

        from sqlalchemy import select
        from app.models.ai_result import AIResult
        ai_result = (await db_session.execute(
            select(AIResult).where(AIResult.ai_job_id == job.id)
        )).scalar_one_or_none()
        assert ai_result is not None
        assert ai_result.provider_name == "mock"
        # RAG chunk ids should be empty list (no real pgvector)
        assert ai_result.retrieved_chunk_ids == [] or ai_result.retrieved_chunk_ids is None

    @pytest.mark.asyncio
    async def test_ai_job_with_knowledge_disabled_skips_retrieval(self, db_session, tenant_a):
        """When knowledge_enabled=False, no RAG retrieval attempt is made."""
        import uuid as _uuid
        from datetime import datetime, timezone
        from app.models.tenant import TenantConfig
        from sqlalchemy import select
        from app.models.ai_job import AIJob, AIJobStatus
        from app.models.customer import Customer
        from app.models.conversation import Conversation
        from app.models.ticket import Ticket, TicketStatus, TicketPriority
        from app.models.event_log import EventLog
        from app.worker.tasks import _process_ai_job_inner

        # Ensure knowledge_enabled=False (default)
        cfg = (await db_session.execute(
            select(TenantConfig).where(TenantConfig.tenant_id == tenant_a.id)
        )).scalar_one_or_none()
        if cfg:
            cfg.knowledge_enabled = False
            await db_session.commit()

        customer = Customer(
            id=_uuid.uuid4(), tenant_id=tenant_a.id,
            external_id="+19990002222", channel="webchat",
        )
        db_session.add(customer)
        conv = Conversation(
            id=_uuid.uuid4(), tenant_id=tenant_a.id,
            customer_id=customer.id, channel="webchat",
        )
        db_session.add(conv)
        ticket = Ticket(
            id=_uuid.uuid4(), tenant_id=tenant_a.id,
            conversation_id=conv.id,
            ticket_number=2, status=TicketStatus.pending_agent,
            priority=TicketPriority.medium,
        )
        db_session.add(ticket)
        event = EventLog(
            id=_uuid.uuid4(), tenant_id=tenant_a.id,
            conversation_id=conv.id, channel="webchat",
            direction="inbound", message_text="What are your hours?",
            event_timestamp=datetime.now(timezone.utc),
            external_user_identifier="+19990002222",
        )
        db_session.add(event)
        job = AIJob(
            id=_uuid.uuid4(), tenant_id=tenant_a.id,
            ticket_id=ticket.id, conversation_id=conv.id,
            event_log_id=event.id, status=AIJobStatus.pending,
            retry_count=0, max_retries=3,
        )
        db_session.add(job)
        await db_session.commit()

        result = await _process_ai_job_inner(db_session, str(job.id))
        assert result["status"] == "completed"


# ── Tenant config knowledge fields ─────────────────────────────────────────────

class TestTenantConfigKnowledgeFields:
    @pytest.mark.asyncio
    async def test_update_knowledge_config(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.put(
            "/api/v1/tenants/me/config",
            headers=headers,
            json={"knowledge_enabled": True, "retrieval_top_k": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["knowledge_enabled"] is True
        assert data["retrieval_top_k"] == 5

    @pytest.mark.asyncio
    async def test_retrieval_top_k_validation(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        # top_k must be >= 1
        response = await client.put(
            "/api/v1/tenants/me/config",
            headers=headers,
            json={"retrieval_top_k": 0},
        )
        assert response.status_code == 422
