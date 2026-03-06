"""
Unit tests for the AI worker task (_process_ai_job_inner).

Tests are fully self-contained — they use the in-memory SQLite DB
and call the inner function directly without any Redis/ARQ dependency.
"""
import uuid
import pytest
import pytest_asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.tenant import Tenant, TenantConfig
from app.models.user import User, UserRole
from app.models.customer import Customer
from app.models.conversation import Conversation
from app.models.ticket import Ticket, TicketStatus, TicketPriority
from app.models.event_log import EventLog
from app.models.ai_job import AIJob, AIJobStatus
from app.models.ai_result import AIResult
from app.core.security import hash_password
from app.worker.tasks import _process_ai_job_inner

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


# ── DB fixtures ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session


# ── Entity builders ───────────────────────────────────────────────────────────

async def _create_full_stack(db: AsyncSession, ai_enabled: bool = True):
    """Create Tenant → Customer → Conversation → Ticket → EventLog → AIJob."""
    tenant = Tenant(id=uuid.uuid4(), name="T", slug="t-worker", is_active=True, plan="starter")
    db.add(tenant)
    cfg = TenantConfig(
        tenant_id=tenant.id,
        ai_enabled=ai_enabled,
        auto_send_mode="off",
        confidence_threshold=0.7,
    )
    db.add(cfg)

    customer = Customer(
        id=uuid.uuid4(), tenant_id=tenant.id, external_id="+1234", channel="whatsapp"
    )
    db.add(customer)

    conversation = Conversation(
        id=uuid.uuid4(), tenant_id=tenant.id, customer_id=customer.id, channel="whatsapp"
    )
    db.add(conversation)

    ticket = Ticket(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        status=TicketStatus.pending_agent,
        priority=TicketPriority.medium,
        ticket_number=1,
        title="Test",
    )
    db.add(ticket)

    event_log = EventLog(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        channel="whatsapp",
        external_user_identifier="+1234",
        message_text="Hello there",
        event_timestamp=datetime.now(timezone.utc),
        direction="inbound",
    )
    db.add(event_log)

    job = AIJob(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        ticket_id=ticket.id,
        conversation_id=conversation.id,
        event_log_id=event_log.id,
        status=AIJobStatus.pending,
        retry_count=0,
        max_retries=3,
    )
    db.add(job)
    await db.commit()
    return tenant, ticket, conversation, event_log, job


# ── Idempotency tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_pending_job_completes(db):
    _, _, _, _, job = await _create_full_stack(db)
    result = await _process_ai_job_inner(db, str(job.id))
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_idempotent_already_completed(db):
    """Calling process on a completed job is a no-op."""
    _, _, _, _, job = await _create_full_stack(db)
    # Process once
    await _process_ai_job_inner(db, str(job.id))
    # Process again
    result = await _process_ai_job_inner(db, str(job.id))
    assert result["status"] == "skipped"
    assert result["reason"] == "already_completed"


@pytest.mark.asyncio
async def test_idempotent_max_retries_exceeded(db):
    """Jobs that have hit max retries are not re-processed."""
    _, _, _, _, job = await _create_full_stack(db)
    job.status = AIJobStatus.failed
    job.retry_count = 3
    job.max_retries = 3
    await db.commit()

    result = await _process_ai_job_inner(db, str(job.id))
    assert result["status"] == "skipped"
    assert result["reason"] == "max_retries_exceeded"


@pytest.mark.asyncio
async def test_nonexistent_job_returns_not_found(db):
    result = await _process_ai_job_inner(db, str(uuid.uuid4()))
    assert result["status"] == "not_found"


# ── AI result creation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_result_persisted_after_completion(db):
    from sqlalchemy import select
    _, ticket, _, _, job = await _create_full_stack(db)

    await _process_ai_job_inner(db, str(job.id))

    result = await db.execute(select(AIResult).where(AIResult.ai_job_id == job.id))
    ai_result = result.scalar_one_or_none()
    assert ai_result is not None
    assert ai_result.ticket_id == ticket.id
    assert ai_result.intent is not None
    assert ai_result.confidence is not None
    assert ai_result.provider_name == "mock"


@pytest.mark.asyncio
async def test_ticket_remains_pending_agent_after_ai(db):
    """Phase 2: ticket status must NOT change after AI processing."""
    from sqlalchemy import select
    _, ticket, _, _, job = await _create_full_stack(db)

    await _process_ai_job_inner(db, str(job.id))

    refreshed = await db.execute(select(Ticket).where(Ticket.id == ticket.id))
    ticket_row = refreshed.scalar_one()
    assert ticket_row.status == TicketStatus.pending_agent


# ── Retry behaviour ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_error_increments_retry_count(db):
    """When the AI provider raises, retry_count increments and job goes back to pending."""
    from unittest.mock import AsyncMock, patch
    _, _, _, _, job = await _create_full_stack(db)

    with patch("app.worker.tasks.get_ai_provider") as mock_get_provider:
        mock_provider = AsyncMock()
        mock_provider.generate_decision.side_effect = RuntimeError("Provider error")
        mock_get_provider.return_value = mock_provider

        result = await _process_ai_job_inner(db, str(job.id))

    # Should be pending again (can be retried) since retry_count < max_retries
    from sqlalchemy import select
    refreshed = await db.execute(select(AIJob).where(AIJob.id == job.id))
    job_row = refreshed.scalar_one()
    assert job_row.retry_count == 1
    assert job_row.status == AIJobStatus.pending
    assert "error" in result


@pytest.mark.asyncio
async def test_max_retries_marks_failed(db):
    """After max_retries errors, job status becomes 'failed'."""
    from unittest.mock import AsyncMock, patch
    _, _, _, _, job = await _create_full_stack(db)
    job.retry_count = 2  # One away from max_retries=3
    job.max_retries = 3
    await db.commit()

    with patch("app.worker.tasks.get_ai_provider") as mock_get_provider:
        mock_provider = AsyncMock()
        mock_provider.generate_decision.side_effect = RuntimeError("Fatal error")
        mock_get_provider.return_value = mock_provider

        await _process_ai_job_inner(db, str(job.id))

    from sqlalchemy import select
    refreshed = await db.execute(select(AIJob).where(AIJob.id == job.id))
    job_row = refreshed.scalar_one()
    assert job_row.status == AIJobStatus.failed
    assert job_row.retry_count == 3


# ── Policy behaviour ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_escalation_message_not_safe_to_auto_send(db):
    """Escalation intent → safe_to_auto_send must be False."""
    from sqlalchemy import select
    # Use a refund message to trigger escalation
    tenant, _, conversation, _, job = await _create_full_stack(db)

    # Replace event_log with an escalation-triggering message
    event_log_result = await db.execute(
        select(EventLog).where(EventLog.conversation_id == conversation.id)
    )
    event_log = event_log_result.scalar_one()
    event_log.message_text = "I want a refund immediately!"
    await db.commit()

    await _process_ai_job_inner(db, str(job.id))

    result_row = await db.execute(select(AIResult).where(AIResult.ai_job_id == job.id))
    ai_result = result_row.scalar_one()
    assert ai_result.should_escalate is True
    assert ai_result.safe_to_auto_send is False


@pytest.mark.asyncio
async def test_safe_greeting_with_auto_mode(db):
    """Greeting in auto mode → safe_to_auto_send True."""
    from sqlalchemy import select
    tenant, _, conversation, _, job = await _create_full_stack(db)

    # Set auto_send_mode=auto for the tenant
    cfg_result = await db.execute(
        select(TenantConfig).where(TenantConfig.tenant_id == tenant.id)
    )
    cfg = cfg_result.scalar_one()
    cfg.auto_send_mode = "auto"
    cfg.confidence_threshold = 0.5
    await db.commit()

    # Set greeting message
    event_log_result = await db.execute(
        select(EventLog).where(EventLog.conversation_id == conversation.id)
    )
    event_log = event_log_result.scalar_one()
    event_log.message_text = "Hello, good morning!"
    await db.commit()

    await _process_ai_job_inner(db, str(job.id))

    result_row = await db.execute(select(AIResult).where(AIResult.ai_job_id == job.id))
    ai_result = result_row.scalar_one()
    assert ai_result.should_escalate is False
    assert ai_result.safe_to_auto_send is True


@pytest.mark.asyncio
async def test_fallback_when_provider_unavailable(db):
    """When provider raises, job is retried not crashed — inbound stays intact."""
    from unittest.mock import AsyncMock, patch
    _, _, _, _, job = await _create_full_stack(db)

    with patch("app.worker.tasks.get_ai_provider") as mock_get_provider:
        mock_provider = AsyncMock()
        mock_provider.generate_decision.side_effect = ConnectionError("LLM unavailable")
        mock_get_provider.return_value = mock_provider

        result = await _process_ai_job_inner(db, str(job.id))

    # Job should not be 'failed' yet (first error)
    from sqlalchemy import select
    refreshed = await db.execute(select(AIJob).where(AIJob.id == job.id))
    job_row = refreshed.scalar_one()
    assert job_row.status in (AIJobStatus.pending, AIJobStatus.failed)
    assert "error" in result
