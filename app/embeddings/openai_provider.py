"""
OpenAI embedding provider — Phase 3.

Uses the openai async client to generate real embeddings via
OpenAI's text-embedding API (default: text-embedding-3-small, 1536 dims).

Configure via:
  EMBEDDING_PROVIDER=openai
  OPENAI_API_KEY=sk-...
  OPENAI_EMBEDDING_MODEL=text-embedding-3-small  (default)
  EMBEDDING_DIMENSIONS=1536                       (default)
"""
from typing import List

from app.embeddings.base import BaseEmbeddingProvider
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """
    Embedding provider backed by the OpenAI Embeddings API.
    Requires: pip install openai, and OPENAI_API_KEY set.
    """

    def __init__(self, api_key: str, model: str, dimensions: int):
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._client = None  # lazy initialised

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "openai package is required for OpenAIEmbeddingProvider. "
                    "Install it with: pip install openai"
                ) from exc
            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_text(self, text: str) -> List[float]:
        client = self._get_client()
        response = await client.embeddings.create(
            input=[text],
            model=self._model,
            dimensions=self._dimensions,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed all texts in a single API call (OpenAI supports batch input)."""
        if not texts:
            return []
        client = self._get_client()
        response = await client.embeddings.create(
            input=texts,
            model=self._model,
            dimensions=self._dimensions,
        )
        # Results are returned in the same order as the input
        ordered = sorted(response.data, key=lambda d: d.index)
        return [item.embedding for item in ordered]

    async def health_check(self) -> bool:
        try:
            await self.embed_text("health check")
            return True
        except Exception as exc:
            logger.warning("openai_embedding_health_check_failed", error=str(exc))
            return False


def get_embedding_provider() -> BaseEmbeddingProvider:
    """
    Factory: return the configured embedding provider.

    Falls back to MockEmbeddingProvider if EMBEDDING_PROVIDER is not 'openai'
    or if OPENAI_API_KEY is absent.
    """
    if settings.EMBEDDING_PROVIDER == "openai" and settings.OPENAI_API_KEY:
        return OpenAIEmbeddingProvider(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_EMBEDDING_MODEL,
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
    from app.embeddings.mock_provider import MockEmbeddingProvider
    return MockEmbeddingProvider()
