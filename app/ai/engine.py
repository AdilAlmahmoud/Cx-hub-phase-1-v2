"""
AI Decision Engine.

Thin orchestration layer that:
1. Selects the configured AI provider (mock or real)
2. Calls provider.generate_decision(context)
3. Enforces tenant-level policy overrides (auto_send_mode)
4. Returns a validated AIDecisionResult
"""
from app.ai.base import BaseAIProvider, AIProcessingContext, AIDecisionResult
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def get_ai_provider() -> BaseAIProvider:
    """
    Factory: return the configured AI provider instance.
    Defaults to MockAIProvider if AI_PROVIDER=mock or no API key is set.
    """
    if settings.AI_PROVIDER == "openai" and settings.OPENAI_API_KEY:
        from app.ai.openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL,
        )
    from app.ai.mock_provider import MockAIProvider
    return MockAIProvider()


class AIDecisionEngine:
    """
    Orchestrates a single AI decision run.

    Usage::
        engine = AIDecisionEngine(provider=get_ai_provider())
        result = await engine.process(context)
    """

    def __init__(self, provider: BaseAIProvider):
        self.provider = provider

    async def process(self, context: AIProcessingContext) -> AIDecisionResult:
        logger.info(
            "ai_engine_start",
            ai_job_id=context.ai_job_id,
            tenant_id=context.tenant_id,
            ticket_id=context.ticket_id,
            provider=self.provider.provider_name,
            channel=context.channel,
        )
        try:
            result = await self.provider.generate_decision(context)
        except Exception as exc:
            logger.error(
                "ai_provider_error",
                ai_job_id=context.ai_job_id,
                provider=self.provider.provider_name,
                error=str(exc),
            )
            raise

        # Policy enforcement: if auto_send_mode is not "auto", ensure
        # safe_to_auto_send is never True regardless of provider output.
        if context.auto_send_mode != "auto" and result.safe_to_auto_send:
            result = result.model_copy(update={"safe_to_auto_send": False})

        logger.info(
            "ai_engine_result",
            ai_job_id=context.ai_job_id,
            tenant_id=context.tenant_id,
            ticket_id=context.ticket_id,
            intent=result.intent,
            confidence=result.confidence,
            should_escalate=result.should_escalate,
            safe_to_auto_send=result.safe_to_auto_send,
            risk_flags=result.risk_flags,
        )
        return result
