"""
OpenAI GPT provider — stub for Phase 2.

Real implementation is deferred to a later phase when:
  - System prompt / RAG integration is defined
  - Knowledge base ingestion is complete
  - Prompt engineering is finalised

To use this stub in Phase 3+, install the openai package and complete
the generate_decision() method body.
"""
from app.ai.base import BaseAIProvider, AIProcessingContext, AIDecisionResult


class OpenAIProvider(BaseAIProvider):
    """
    Stub OpenAI provider.  Raises NotImplementedError until implemented.
    Configure via: AI_PROVIDER=openai, OPENAI_API_KEY=sk-...
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self._api_key = api_key
        self._model = model

    @property
    def provider_name(self) -> str:
        return "openai"

    async def generate_decision(self, context: AIProcessingContext) -> AIDecisionResult:
        raise NotImplementedError(
            "OpenAI provider is not yet implemented. "
            "Set AI_PROVIDER=mock to use the built-in mock provider."
        )

    async def health_check(self) -> bool:
        # Connectivity check deferred to Phase 3 implementation
        return False
