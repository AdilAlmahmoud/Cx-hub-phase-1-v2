"""
Embedding provider abstraction — Phase 3.

All providers implement BaseEmbeddingProvider so the ingestion pipeline
and retrieval service are decoupled from the specific model in use.

Env-driven selection:
  EMBEDDING_PROVIDER=mock    → MockEmbeddingProvider (default, no API key)
  EMBEDDING_PROVIDER=openai  → OpenAIEmbeddingProvider (requires OPENAI_API_KEY)
"""
from abc import ABC, abstractmethod
from typing import List


class BaseEmbeddingProvider(ABC):
    """Abstract base class for all embedding providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short identifier, e.g. 'mock', 'openai'."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier string returned with results."""
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Number of dimensions in the embedding vector."""
        ...

    @abstractmethod
    async def embed_text(self, text: str) -> List[float]:
        """Embed a single piece of text; return a vector of floats."""
        ...

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a list of texts in one call.
        Default implementation calls embed_text sequentially; providers may
        override for true batch efficiency.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable and ready."""
        ...
