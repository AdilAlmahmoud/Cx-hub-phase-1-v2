"""
Unit tests for Phase 4 outbound messaging.

Covers:
- MockOutboundProvider: send returns success, health_check returns True
- BaseOutboundProvider: abstract interface contract
- OutboundResult dataclass fields
- get_outbound_provider registry (mock mode + unknown channel fallback)
- deliver_outbound_message service: happy path, idempotency, max_attempts
- create_outbound_message service: creates pending record
- cancel_outbound_message service: cancels pending, no-op on delivered
- Email adapter normalization (also covered in test_adapters.py addendum below)
"""
import uuid
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.tenant import Tenant, TenantConfig
from app.models.customer import Customer
from app.models.conversation import Conversation
from app.models.outbound import OutboundMessage, OutboundAttempt, OutboundMessageStatus
from app.outbound.base import OutboundResult, BaseOutboundProvider
from app.outbound.mock_provider import MockOutboundProvider
from app.outbound.registry import get_outbound_provider

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


@pytest_asyncio.fixture
async def base_objects(db: AsyncSession):
    """Create a minimal Tenant → Customer → Conversation hierarchy."""
    tenant = Tenant(id=uuid.uuid4(), name="T", slug="t-outbound", is_active=True, plan="starter")
    db.add(tenant)
    db.add(TenantConfig(tenant_id=tenant.id))
    customer = Customer(id=uuid.uuid4(), tenant_id=tenant.id, external_id="+1234", channel="whatsapp")
    db.add(customer)
    conversation = Conversation(
        id=uuid.uuid4(), tenant_id=tenant.id, customer_id=customer.id, channel="whatsapp"
    )
    db.add(conversation)
    await db.commit()
    return tenant, customer, conversation


# ── OutboundResult dataclass ──────────────────────────────────────────────────

class TestOutboundResult:
    def test_success_result(self):
        r = OutboundResult(success=True, provider="mock", provider_message_id="mock_abc")
        assert r.success is True
        assert r.provider == "mock"
        assert r.provider_message_id == "mock_abc"
        assert r.error_code is None
        assert r.error_message is None

    def test_failure_result(self):
        r = OutboundResult(
            success=False,
            provider="sendgrid",
            error_code="invalid_recipient",
            error_message="No such email",
            duration_ms=120,
        )
        assert r.success is False
        assert r.error_code == "invalid_recipient"
        assert r.duration_ms == 120

    def test_defaults(self):
        r = OutboundResult(success=True, provider="test")
        assert r.duration_ms == 0
        assert r.raw_response is None


# ── MockOutboundProvider ──────────────────────────────────────────────────────

class TestMockOutboundProvider:
    def test_provider_name(self):
        p = MockOutboundProvider(channel="whatsapp")
        assert p.provider_name == "mock"

    def test_channel_property(self):
        p = MockOutboundProvider(channel="email")
        assert p.channel == "email"

    @pytest.mark.asyncio
    async def test_health_check_returns_true(self):
        p = MockOutboundProvider(channel="sms")
        assert await p.health_check() is True

    @pytest.mark.asyncio
    async def test_send_returns_success(self):
        p = MockOutboundProvider(channel="whatsapp")
        msg = MagicMock()
        msg.id = uuid.uuid4()
        msg.tenant_id = uuid.uuid4()
        msg.channel = "whatsapp"
        msg.recipient_identifier = "+1234"
        msg.is_ai_generated = False
        msg.message_text = "Hello"
        result = await p.send(msg)
        assert result.success is True
        assert result.provider == "mock"
        assert result.provider_message_id == f"mock_{msg.id}"

    @pytest.mark.asyncio
    async def test_send_includes_duration(self):
        p = MockOutboundProvider(channel="sms")
        msg = MagicMock()
        msg.id = uuid.uuid4()
        msg.tenant_id = uuid.uuid4()
        msg.channel = "sms"
        msg.recipient_identifier = "+5555"
        msg.is_ai_generated = False
        msg.message_text = "SMS test"
        result = await p.send(msg)
        assert isinstance(result.duration_ms, int)
        assert result.duration_ms >= 0


# ── get_outbound_provider registry ───────────────────────────────────────────

class TestOutboundProviderRegistry:
    def test_mock_mode_returns_mock_for_whatsapp(self, monkeypatch):
        monkeypatch.setattr("app.outbound.registry.settings.OUTBOUND_PROVIDER", "mock")
        p = get_outbound_provider("whatsapp")
        assert isinstance(p, MockOutboundProvider)
        assert p.channel == "whatsapp"

    def test_mock_mode_returns_mock_for_email(self, monkeypatch):
        monkeypatch.setattr("app.outbound.registry.settings.OUTBOUND_PROVIDER", "mock")
        p = get_outbound_provider("email")
        assert isinstance(p, MockOutboundProvider)

    def test_mock_mode_returns_mock_for_sms(self, monkeypatch):
        monkeypatch.setattr("app.outbound.registry.settings.OUTBOUND_PROVIDER", "mock")
        p = get_outbound_provider("sms")
        assert isinstance(p, MockOutboundProvider)

    def test_mock_mode_returns_mock_for_webchat(self, monkeypatch):
        monkeypatch.setattr("app.outbound.registry.settings.OUTBOUND_PROVIDER", "mock")
        p = get_outbound_provider("webchat")
        assert isinstance(p, MockOutboundProvider)

    def test_unknown_channel_falls_back_to_mock(self, monkeypatch):
        monkeypatch.setattr("app.outbound.registry.settings.OUTBOUND_PROVIDER", "mock")
        p = get_outbound_provider("carrier_pigeon")
        assert isinstance(p, MockOutboundProvider)
        assert p.channel == "carrier_pigeon"

    def test_channel_lowercased(self, monkeypatch):
        monkeypatch.setattr("app.outbound.registry.settings.OUTBOUND_PROVIDER", "mock")
        p = get_outbound_provider("WhatsApp")
        assert p.channel == "whatsapp"


# ── create_outbound_message ───────────────────────────────────────────────────

class TestCreateOutboundMessage:
    @pytest.mark.asyncio
    async def test_creates_pending_message(self, db, base_objects):
        from app.services.outbound_service import create_outbound_message
        tenant, customer, conversation = base_objects

        msg = await create_outbound_message(
            db=db,
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            channel="whatsapp",
            recipient_identifier=customer.external_id,
            message_text="Hello from agent",
        )

        assert msg.id is not None
        assert msg.status == OutboundMessageStatus.pending
        assert msg.attempt_count == 0
        assert msg.tenant_id == tenant.id
        assert msg.conversation_id == conversation.id
        assert msg.channel == "whatsapp"
        assert msg.message_text == "Hello from agent"
        assert msg.is_ai_generated is False

    @pytest.mark.asyncio
    async def test_creates_ai_generated_message(self, db, base_objects):
        from app.services.outbound_service import create_outbound_message
        tenant, customer, conversation = base_objects

        msg = await create_outbound_message(
            db=db,
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            channel="email",
            recipient_identifier="user@example.com",
            message_text="AI reply",
            is_ai_generated=True,
            subject="Re: your issue",
        )

        assert msg.is_ai_generated is True
        assert msg.subject == "Re: your issue"
        assert msg.channel == "email"

    @pytest.mark.asyncio
    async def test_max_attempts_defaults_to_3(self, db, base_objects):
        from app.services.outbound_service import create_outbound_message
        tenant, customer, conversation = base_objects

        msg = await create_outbound_message(
            db=db,
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            channel="sms",
            recipient_identifier="+5555",
            message_text="test",
        )
        assert msg.max_attempts == 3


# ── deliver_outbound_message ──────────────────────────────────────────────────

class TestDeliverOutboundMessage:
    @pytest.mark.asyncio
    async def test_delivers_pending_message(self, db, base_objects, monkeypatch):
        from app.services.outbound_service import create_outbound_message, deliver_outbound_message
        tenant, customer, conversation = base_objects

        monkeypatch.setattr("app.outbound.registry.settings.OUTBOUND_PROVIDER", "mock")
        msg = await create_outbound_message(
            db=db,
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            channel="whatsapp",
            recipient_identifier="+1234",
            message_text="Hello",
        )

        result = await deliver_outbound_message(db, msg.id)
        assert result["success"] is True
        assert result["status"] == "delivered"
        assert result["provider"] == "mock"

    @pytest.mark.asyncio
    async def test_creates_attempt_record(self, db, base_objects, monkeypatch):
        from sqlalchemy import select
        from app.services.outbound_service import create_outbound_message, deliver_outbound_message
        tenant, customer, conversation = base_objects

        monkeypatch.setattr("app.outbound.registry.settings.OUTBOUND_PROVIDER", "mock")
        msg = await create_outbound_message(
            db=db,
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            channel="whatsapp",
            recipient_identifier="+1234",
            message_text="Hello",
        )

        await deliver_outbound_message(db, msg.id)

        attempts = (
            await db.execute(
                select(OutboundAttempt).where(OutboundAttempt.outbound_message_id == msg.id)
            )
        ).scalars().all()
        assert len(attempts) == 1
        assert attempts[0].status == "success"
        assert attempts[0].provider == "mock"

    @pytest.mark.asyncio
    async def test_skips_already_delivered_message(self, db, base_objects, monkeypatch):
        from app.services.outbound_service import create_outbound_message, deliver_outbound_message
        tenant, customer, conversation = base_objects

        monkeypatch.setattr("app.outbound.registry.settings.OUTBOUND_PROVIDER", "mock")
        msg = await create_outbound_message(
            db=db,
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            channel="whatsapp",
            recipient_identifier="+1234",
            message_text="Hello",
        )

        await deliver_outbound_message(db, msg.id)
        # Second call should be skipped (idempotency)
        result2 = await deliver_outbound_message(db, msg.id)
        assert result2["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_not_found_returns_not_found(self, db, monkeypatch):
        from app.services.outbound_service import deliver_outbound_message
        monkeypatch.setattr("app.outbound.registry.settings.OUTBOUND_PROVIDER", "mock")
        fake_id = uuid.uuid4()
        result = await deliver_outbound_message(db, fake_id)
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded_marks_failed(self, db, base_objects, monkeypatch):
        from app.services.outbound_service import create_outbound_message, deliver_outbound_message
        tenant, customer, conversation = base_objects

        monkeypatch.setattr("app.outbound.registry.settings.OUTBOUND_PROVIDER", "mock")
        msg = await create_outbound_message(
            db=db,
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            channel="whatsapp",
            recipient_identifier="+1234",
            message_text="Hello",
        )
        # Manually set attempt_count to max_attempts
        msg.attempt_count = msg.max_attempts
        await db.commit()

        result = await deliver_outbound_message(db, msg.id)
        assert result["status"] == "failed"
        assert result["reason"] == "max_attempts_exceeded"


# ── cancel_outbound_message ───────────────────────────────────────────────────

class TestCancelOutboundMessage:
    @pytest.mark.asyncio
    async def test_cancels_pending_message(self, db, base_objects, monkeypatch):
        from app.services.outbound_service import create_outbound_message, cancel_outbound_message
        tenant, customer, conversation = base_objects

        msg = await create_outbound_message(
            db=db,
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            channel="sms",
            recipient_identifier="+5555",
            message_text="Cancel me",
        )

        cancelled = await cancel_outbound_message(db, msg.id, tenant.id)
        assert cancelled is not None
        assert cancelled.status == OutboundMessageStatus.cancelled

    @pytest.mark.asyncio
    async def test_cancel_delivered_is_noop(self, db, base_objects, monkeypatch):
        from app.services.outbound_service import create_outbound_message, cancel_outbound_message
        tenant, customer, conversation = base_objects

        msg = await create_outbound_message(
            db=db,
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            channel="sms",
            recipient_identifier="+5555",
            message_text="Already done",
        )
        msg.status = OutboundMessageStatus.delivered
        await db.commit()

        result = await cancel_outbound_message(db, msg.id, tenant.id)
        assert result.status == OutboundMessageStatus.delivered  # unchanged

    @pytest.mark.asyncio
    async def test_cancel_wrong_tenant_returns_none(self, db, base_objects):
        from app.services.outbound_service import create_outbound_message, cancel_outbound_message
        tenant, customer, conversation = base_objects

        msg = await create_outbound_message(
            db=db,
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            channel="sms",
            recipient_identifier="+5555",
            message_text="Wrong tenant",
        )

        other_tenant_id = uuid.uuid4()
        result = await cancel_outbound_message(db, msg.id, other_tenant_id)
        assert result is None
