"""
Mock embedding provider — deterministic, no external API calls.

Uses a SHA-256 hash of the input text to seed a deterministic pseudo-random
vector.  The same text always produces the same embedding so retrieval tests
are reproducible.

Dimensions: 1536 (matching OpenAI text-embedding-3-small) so embeddings are
drop-in compatible with the pgvector column definition.
"""
import hashlib
import math
from typing import List

from app.embeddings.base import BaseEmbeddingProvider

_DIMS = 1536


def _deterministic_embedding(text: str, dims: int = _DIMS) -> List[float]:
    """
    Generate a deterministic unit-length embedding from the SHA-256 hash of *text*.

    The hash is expanded to *dims* floats by cycling through the digest bytes,
    then the vector is L2-normalised so cosine similarity makes sense.
    """
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).digest()
    # Expand digest bytes into floats in [-1, 1]
    raw: List[float] = []
    for i in range(dims):
        byte_val = digest[i % len(digest)]
        # Mix position to avoid repeating patterns
        mixed = (byte_val ^ (i & 0xFF)) / 127.5 - 1.0
        raw.append(mixed)

    # L2 normalise
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """
    Deterministic mock embedding provider.

    Used by default (EMBEDDING_PROVIDER=mock) and in all automated tests.
    No network calls, no API key required.
    """

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-embedding-v1"

    @property
    def dimensions(self) -> int:
        return _DIMS

    async def embed_text(self, text: str) -> List[float]:
        return _deterministic_embedding(text, _DIMS)

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [_deterministic_embedding(t, _DIMS) for t in texts]

    async def health_check(self) -> bool:
        return True
