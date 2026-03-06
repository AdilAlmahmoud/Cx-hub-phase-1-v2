"""
Unit tests for the AI decision engine and mock provider.

These tests run without any database, Redis, or external API.
"""
import pytest
from datetime import datetime, timezone

from app.ai.base import AIProcessingContext, AIDecisionResult, ConversationMessage
from app.ai.mock_provider import MockAIProvider, _detect_intent
from app.ai.engine import AIDecisionEngine, get_ai_provider


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_context(**overrides) -> AIProcessingContext:
    defaults = dict(
        ai_job_id="job-123",
        tenant_id="tenant-abc",
        ticket_id="ticket-xyz",
        conversation_id="conv-001",
        message_text="Hello, I need help",
        channel="whatsapp",
        ai_language="en",
        ai_tone="professional",
        confidence_threshold=0.7,
        auto_send_mode="off",
        escalation_keywords=[],
    )
    defaults.update(overrides)
    return AIProcessingContext(**defaults)


# ── Intent detection ───────────────────────────────────────────────────────────

class TestIntentDetection:
    def test_greeting_detected(self):
        assert _detect_intent("Hello there!", []) == "greeting"

    def test_hi_greeting(self):
        assert _detect_intent("hi how are you", []) == "greeting"

    def test_refund_detected(self):
        assert _detect_intent("I want a refund for my order", []) == "refund_request"

    def test_complaint_detected(self):
        assert _detect_intent("The service was terrible and awful!", []) == "complaint"

    def test_legal_detected(self):
        assert _detect_intent("I will sue you", []) == "legal_threat"

    def test_emergency_detected(self):
        assert _detect_intent("It is urgent please respond asap", []) == "emergency"

    def test_status_inquiry_detected(self):
        assert _detect_intent("Can you check my order status?", []) == "status_inquiry"

    def test_faq_detected(self):
        assert _detect_intent("How do I change my password?", []) == "faq"

    def test_general_inquiry_fallback(self):
        assert _detect_intent("I would like some assistance please", []) == "general_inquiry"

    def test_empty_message_returns_unknown(self):
        assert _detect_intent("", []) == "unknown"

    def test_none_message_returns_unknown(self):
        assert _detect_intent(None, []) == "unknown"

    def test_custom_escalation_keyword(self):
        intent = _detect_intent("I need to cancel everything", ["cancel"])
        assert intent == "escalation_keyword_match"

    def test_custom_keyword_case_insensitive(self):
        intent = _detect_intent("Please CANCEL my account", ["cancel"])
        assert intent == "escalation_keyword_match"

    def test_custom_keyword_priority_over_safe_intent(self):
        # Even if message looks like a greeting, escalation keyword wins
        intent = _detect_intent("Hello I want to escalate", ["escalate"])
        assert intent == "escalation_keyword_match"


# ── MockAIProvider ─────────────────────────────────────────────────────────────

class TestMockAIProvider:
    @pytest.fixture
    def provider(self):
        return MockAIProvider()

    def test_provider_name(self, provider):
        assert provider.provider_name == "mock"

    @pytest.mark.asyncio
    async def test_health_check_returns_true(self, provider):
        assert await provider.health_check() is True

    @pytest.mark.asyncio
    async def test_returns_ai_decision_result(self, provider):
        ctx = make_context(message_text="Hello!")
        result = await provider.generate_decision(ctx)
        assert isinstance(result, AIDecisionResult)

    @pytest.mark.asyncio
    async def test_greeting_not_escalated(self, provider):
        ctx = make_context(message_text="Hello, good morning!")
        result = await provider.generate_decision(ctx)
        assert result.intent == "greeting"
        assert result.should_escalate is False
        assert result.answer is not None

    @pytest.mark.asyncio
    async def test_refund_escalated(self, provider):
        ctx = make_context(message_text="I want a refund now!")
        result = await provider.generate_decision(ctx)
        assert result.should_escalate is True
        assert result.answer is None
        assert result.escalation_reason is not None
        assert "escalation_intent:refund_request" in result.risk_flags

    @pytest.mark.asyncio
    async def test_complaint_escalated(self, provider):
        ctx = make_context(message_text="The service is absolutely terrible and unacceptable!")
        result = await provider.generate_decision(ctx)
        assert result.should_escalate is True

    @pytest.mark.asyncio
    async def test_legal_escalated(self, provider):
        ctx = make_context(message_text="I will sue your company")
        result = await provider.generate_decision(ctx)
        assert result.should_escalate is True

    @pytest.mark.asyncio
    async def test_auto_send_off_never_safe(self, provider):
        """auto_send_mode=off means safe_to_auto_send is always False."""
        ctx = make_context(message_text="Hello!", auto_send_mode="off")
        result = await provider.generate_decision(ctx)
        assert result.safe_to_auto_send is False

    @pytest.mark.asyncio
    async def test_auto_send_auto_with_high_confidence(self, provider):
        """auto_send_mode=auto + greeting (high confidence) → safe_to_auto_send=True."""
        ctx = make_context(
            message_text="Hello!",
            auto_send_mode="auto",
            confidence_threshold=0.7,
        )
        result = await provider.generate_decision(ctx)
        assert result.intent == "greeting"
        assert result.confidence >= 0.7
        assert result.safe_to_auto_send is True

    @pytest.mark.asyncio
    async def test_auto_send_auto_low_confidence_not_safe(self, provider):
        """If confidence < threshold, safe_to_auto_send stays False even in auto mode."""
        ctx = make_context(
            message_text="Hello!",
            auto_send_mode="auto",
            confidence_threshold=0.99,  # artificially high threshold
        )
        result = await provider.generate_decision(ctx)
        # Greeting confidence is 0.9 < 0.99 → not safe
        assert result.safe_to_auto_send is False

    @pytest.mark.asyncio
    async def test_supervised_mode_draft_present_not_safe(self, provider):
        """auto_send_mode=supervised: draft is generated but safe_to_auto_send=False."""
        ctx = make_context(message_text="Hello!", auto_send_mode="supervised")
        result = await provider.generate_decision(ctx)
        assert result.answer is not None
        assert result.safe_to_auto_send is False

    @pytest.mark.asyncio
    async def test_escalation_keyword_triggers_escalation(self, provider):
        ctx = make_context(
            message_text="I want to speak to management",
            escalation_keywords=["management"],
        )
        result = await provider.generate_decision(ctx)
        assert result.should_escalate is True

    @pytest.mark.asyncio
    async def test_long_message_adds_risk_flag(self, provider):
        ctx = make_context(message_text="x" * 1001)
        result = await provider.generate_decision(ctx)
        assert "long_message" in result.risk_flags

    @pytest.mark.asyncio
    async def test_confidence_in_range(self, provider):
        ctx = make_context(message_text="Tell me about your services")
        result = await provider.generate_decision(ctx)
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_provider_name_in_result(self, provider):
        ctx = make_context(message_text="Hello")
        result = await provider.generate_decision(ctx)
        assert result.provider_name == "mock"
        assert result.model_name == "mock-v1"

    @pytest.mark.asyncio
    async def test_processing_duration_non_negative(self, provider):
        ctx = make_context(message_text="Hello")
        result = await provider.generate_decision(ctx)
        assert result.processing_duration_ms >= 0


# ── AIDecisionEngine ──────────────────────────────────────────────────────────

class TestAIDecisionEngine:
    @pytest.fixture
    def engine(self):
        return AIDecisionEngine(provider=MockAIProvider())

    @pytest.mark.asyncio
    async def test_engine_returns_result(self, engine):
        ctx = make_context(message_text="Hello!")
        result = await engine.process(ctx)
        assert isinstance(result, AIDecisionResult)

    @pytest.mark.asyncio
    async def test_engine_enforces_auto_send_off(self, engine):
        """Engine overrides provider: auto_send_mode=off → safe_to_auto_send always False."""
        ctx = make_context(
            message_text="Hello!",
            auto_send_mode="off",
            confidence_threshold=0.0,  # would normally pass if mode were 'auto'
        )
        result = await engine.process(ctx)
        assert result.safe_to_auto_send is False

    @pytest.mark.asyncio
    async def test_engine_allows_auto_send_in_auto_mode(self, engine):
        ctx = make_context(
            message_text="Hello!",
            auto_send_mode="auto",
            confidence_threshold=0.5,
        )
        result = await engine.process(ctx)
        assert result.safe_to_auto_send is True

    @pytest.mark.asyncio
    async def test_engine_propagates_provider_error(self, engine):
        """Engine re-raises exceptions from the provider."""
        class _ErrorProvider:
            provider_name = "error"
            async def generate_decision(self, ctx):
                raise ValueError("provider exploded")
            async def health_check(self):
                return False

        broken_engine = AIDecisionEngine(provider=_ErrorProvider())
        ctx = make_context(message_text="Hello!")
        with pytest.raises(ValueError, match="provider exploded"):
            await broken_engine.process(ctx)


# ── get_ai_provider factory ────────────────────────────────────────────────────

class TestGetAIProvider:
    def test_default_returns_mock(self):
        provider = get_ai_provider()
        assert provider.provider_name == "mock"

    def test_mock_provider_type(self):
        from app.ai.mock_provider import MockAIProvider
        assert isinstance(get_ai_provider(), MockAIProvider)
