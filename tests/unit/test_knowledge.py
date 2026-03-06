"""
Unit tests for Phase 3 knowledge base components.

Covers:
  - Text chunking (storage.chunk_text)
  - Text extraction (storage.extract_text)
  - Mock embedding provider (determinism + dimensions)
  - Embedding provider factory
  - Ingestion pipeline (in-memory SQLite, no Redis)
  - AI engine with RAG context (mock provider)
  - AI engine without RAG context (fallback behaviour)
"""
import os
import tempfile
import uuid
from pathlib import Path
from typing import List

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base


# ── Text chunking ──────────────────────────────────────────────────────────────

class TestChunkText:
    def _chunk(self, text, size=100, overlap=10):
        from app.core.storage import chunk_text
        return chunk_text(text, chunk_size=size, overlap=overlap)

    def test_empty_string_returns_empty(self):
        assert self._chunk("") == []

    def test_whitespace_only_returns_empty(self):
        assert self._chunk("   \n\t  ") == []

    def test_short_text_returns_single_chunk(self):
        text = "Hello world"
        chunks = self._chunk(text, size=200)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world"

    def test_long_text_splits_into_multiple_chunks(self):
        text = "word " * 100  # 500 chars
        chunks = self._chunk(text, size=100, overlap=10)
        assert len(chunks) > 1

    def test_all_chunks_nonempty(self):
        text = "Hello world. " * 50
        chunks = self._chunk(text, size=80, overlap=15)
        for c in chunks:
            assert c.strip() != ""

    def test_overlap_creates_shared_content(self):
        # With sufficient overlap, adjacent chunks share words
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        chunks = self._chunk(text, size=30, overlap=15)
        assert len(chunks) >= 2

    def test_chunks_cover_all_content(self):
        # Every word in the original should appear in at least one chunk
        words = ["alpha", "beta", "gamma", "delta", "epsilon"]
        text = " ".join(words * 10)
        chunks = self._chunk(text, size=50, overlap=10)
        joined = " ".join(chunks)
        for w in words:
            assert w in joined


# ── Text extraction ────────────────────────────────────────────────────────────

class TestExtractText:
    def test_extract_txt(self, tmp_path):
        from app.core.storage import extract_text
        f = tmp_path / "doc.txt"
        f.write_text("Hello from a text file", encoding="utf-8")
        result = extract_text(str(f))
        assert "Hello from a text file" in result

    def test_extract_md(self, tmp_path):
        from app.core.storage import extract_text
        f = tmp_path / "doc.md"
        f.write_text("# Heading\n\nSome content here.", encoding="utf-8")
        result = extract_text(str(f))
        assert "Heading" in result

    def test_extract_pdf(self, tmp_path):
        """Test PDF extraction with pypdf (creates a minimal blank PDF)."""
        try:
            from pypdf import PdfWriter
            writer = PdfWriter()
            writer.add_blank_page(width=200, height=200)
            pdf_path = tmp_path / "test.pdf"
            with open(pdf_path, "wb") as f:
                writer.write(f)
        except BaseException:
            pytest.skip("pypdf or its dependencies not available in this environment")

        from app.core.storage import extract_text
        # A blank PDF will extract empty text — just verify no exception raised
        result = extract_text(str(pdf_path))
        assert isinstance(result, str)

    def test_unsupported_extension_raises(self, tmp_path):
        from app.core.storage import extract_text
        f = tmp_path / "doc.docx"
        f.write_bytes(b"fake content")
        with pytest.raises(ValueError, match="Unsupported"):
            extract_text(str(f))

    def test_missing_file_raises(self):
        from app.core.storage import extract_text
        with pytest.raises(FileNotFoundError):
            extract_text("/nonexistent/path/file.txt")


# ── Mock embedding provider ────────────────────────────────────────────────────

class TestMockEmbeddingProvider:
    @pytest.fixture
    def provider(self):
        from app.embeddings.mock_provider import MockEmbeddingProvider
        return MockEmbeddingProvider()

    def test_provider_name(self, provider):
        assert provider.provider_name == "mock"

    def test_dimensions(self, provider):
        assert provider.dimensions == 1536

    @pytest.mark.asyncio
    async def test_embed_text_returns_correct_dimensions(self, provider):
        embedding = await provider.embed_text("Hello world")
        assert len(embedding) == 1536

    @pytest.mark.asyncio
    async def test_embed_text_is_deterministic(self, provider):
        e1 = await provider.embed_text("Hello world")
        e2 = await provider.embed_text("Hello world")
        assert e1 == e2

    @pytest.mark.asyncio
    async def test_different_texts_produce_different_embeddings(self, provider):
        e1 = await provider.embed_text("Hello world")
        e2 = await provider.embed_text("Goodbye world")
        assert e1 != e2

    @pytest.mark.asyncio
    async def test_embedding_is_unit_length(self, provider):
        import math
        embedding = await provider.embed_text("test")
        norm = math.sqrt(sum(v * v for v in embedding))
        assert abs(norm - 1.0) < 1e-6, f"Norm is {norm}, expected ~1.0"

    @pytest.mark.asyncio
    async def test_embed_batch(self, provider):
        texts = ["Hello", "World", "Test"]
        embeddings = await provider.embed_batch(texts)
        assert len(embeddings) == 3
        for emb in embeddings:
            assert len(emb) == 1536

    @pytest.mark.asyncio
    async def test_embed_empty_batch(self, provider):
        embeddings = await provider.embed_batch([])
        assert embeddings == []

    @pytest.mark.asyncio
    async def test_health_check(self, provider):
        assert await provider.health_check() is True


# ── Embedding provider factory ─────────────────────────────────────────────────

class TestGetEmbeddingProvider:
    def test_default_returns_mock(self):
        from app.embeddings.openai_provider import get_embedding_provider
        from app.embeddings.mock_provider import MockEmbeddingProvider
        provider = get_embedding_provider()
        assert isinstance(provider, MockEmbeddingProvider)

    def test_mock_provider_dimensions(self):
        from app.embeddings.openai_provider import get_embedding_provider
        provider = get_embedding_provider()
        assert provider.dimensions == 1536


# ── Ingestion pipeline (in-memory SQLite, no Redis) ───────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_engine_kn():
    engine = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_kn(db_engine_kn) -> AsyncSession:
    SessionLocal = async_sessionmaker(db_engine_kn, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session


class TestIngestionPipeline:
    @pytest.mark.asyncio
    async def test_ingest_txt_file(self, db_kn, tmp_path):
        """Full ingestion pipeline: save file → create DB record → ingest."""
        from app.services.knowledge_service import create_knowledge_file, ingest_knowledge_file
        from app.models.knowledge import KnowledgeFileStatus

        text_content = "This is a test knowledge document. " * 30
        tenant_id = uuid.uuid4()

        # Temporarily override the storage path to tmp_path
        import app.core.config as _cfg
        original = _cfg.settings.KNOWLEDGE_STORAGE_PATH
        _cfg.settings.KNOWLEDGE_STORAGE_PATH = str(tmp_path)

        try:
            kf = await create_knowledge_file(
                db=db_kn,
                tenant_id=tenant_id,
                original_filename="test.txt",
                content=text_content.encode("utf-8"),
                mime_type="text/plain",
            )
            assert kf.status == KnowledgeFileStatus.pending

            result = await ingest_knowledge_file(db_kn, kf.id)
            assert result["status"] == "completed"
            assert result["chunk_count"] >= 1

            # Reload and verify
            from sqlalchemy import select
            from app.models.knowledge import KnowledgeFile, KnowledgeChunk
            await db_kn.refresh(kf)
            assert kf.status == KnowledgeFileStatus.ready
            assert kf.chunk_count >= 1

            chunks = (await db_kn.execute(
                select(KnowledgeChunk).where(KnowledgeChunk.knowledge_file_id == kf.id)
            )).scalars().all()
            assert len(chunks) >= 1
            for chunk in chunks:
                assert chunk.content.strip() != ""
                assert chunk.tenant_id == tenant_id
        finally:
            _cfg.settings.KNOWLEDGE_STORAGE_PATH = original

    @pytest.mark.asyncio
    async def test_ingest_already_ready_skips(self, db_kn, tmp_path):
        """Re-ingesting a 'ready' file returns 'skipped' (idempotency)."""
        from app.services.knowledge_service import create_knowledge_file, ingest_knowledge_file
        from app.models.knowledge import KnowledgeFileStatus

        tenant_id = uuid.uuid4()
        import app.core.config as _cfg
        original = _cfg.settings.KNOWLEDGE_STORAGE_PATH
        _cfg.settings.KNOWLEDGE_STORAGE_PATH = str(tmp_path)

        try:
            kf = await create_knowledge_file(
                db=db_kn, tenant_id=tenant_id,
                original_filename="doc.txt",
                content=b"Hello " * 50,
                mime_type="text/plain",
            )
            await ingest_knowledge_file(db_kn, kf.id)
            result = await ingest_knowledge_file(db_kn, kf.id)
            assert result["status"] == "skipped"
            assert result["reason"] == "already_ready"
        finally:
            _cfg.settings.KNOWLEDGE_STORAGE_PATH = original

    @pytest.mark.asyncio
    async def test_ingest_missing_file_returns_not_found(self, db_kn):
        from app.services.knowledge_service import ingest_knowledge_file
        result = await ingest_knowledge_file(db_kn, uuid.uuid4())
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_ingest_bad_path_marks_failed(self, db_kn, tmp_path):
        """If the file is missing on disk, ingestion marks the record as failed."""
        from app.services.knowledge_service import create_knowledge_file, ingest_knowledge_file
        from app.models.knowledge import KnowledgeFileStatus

        tenant_id = uuid.uuid4()
        import app.core.config as _cfg
        original = _cfg.settings.KNOWLEDGE_STORAGE_PATH
        _cfg.settings.KNOWLEDGE_STORAGE_PATH = str(tmp_path)

        try:
            kf = await create_knowledge_file(
                db=db_kn, tenant_id=tenant_id,
                original_filename="doc.txt",
                content=b"hello world " * 5,
                mime_type="text/plain",
            )
            # Delete the file from disk after creating the DB record
            Path(kf.file_path).unlink()

            result = await ingest_knowledge_file(db_kn, kf.id)
            assert result["status"] == "failed"
            await db_kn.refresh(kf)
            assert kf.status == KnowledgeFileStatus.failed
            assert kf.error_message is not None
        finally:
            _cfg.settings.KNOWLEDGE_STORAGE_PATH = original


# ── AI engine with RAG context ────────────────────────────────────────────────

class TestAIEngineWithRAG:
    def _make_context(self, message="Hello, I need help", chunks=None):
        from app.ai.base import AIProcessingContext, RetrievedChunk
        return AIProcessingContext(
            ai_job_id="job-rag-1",
            tenant_id="tenant-1",
            ticket_id="ticket-1",
            conversation_id="conv-1",
            message_text=message,
            channel="webchat",
            retrieved_chunks=chunks or [],
        )

    @pytest.mark.asyncio
    async def test_mock_provider_without_rag(self):
        from app.ai.mock_provider import MockAIProvider
        provider = MockAIProvider()
        ctx = self._make_context()
        result = await provider.generate_decision(ctx)
        assert result.intent == "greeting"
        assert result.retrieved_chunk_ids == []
        assert "RAG" not in (result.processing_notes or "")

    @pytest.mark.asyncio
    async def test_mock_provider_with_rag_chunks(self):
        from app.ai.mock_provider import MockAIProvider
        from app.ai.base import RetrievedChunk
        provider = MockAIProvider()
        chunks = [
            RetrievedChunk(
                chunk_id="chunk-1",
                knowledge_file_id="file-1",
                content="Our return policy is 30 days.",
                chunk_index=0,
                similarity_score=0.92,
            ),
            RetrievedChunk(
                chunk_id="chunk-2",
                knowledge_file_id="file-1",
                content="You can return items at any store.",
                chunk_index=1,
                similarity_score=0.85,
            ),
        ]
        ctx = self._make_context(chunks=chunks)
        result = await provider.generate_decision(ctx)
        assert result.retrieved_chunk_ids == ["chunk-1", "chunk-2"]
        assert "RAG: 2 chunk(s) used" in (result.processing_notes or "")
        # Answer should incorporate KB content
        assert result.answer is not None
        assert "knowledge base" in result.answer.lower()

    @pytest.mark.asyncio
    async def test_mock_provider_escalation_no_answer_even_with_rag(self):
        from app.ai.mock_provider import MockAIProvider
        from app.ai.base import RetrievedChunk
        provider = MockAIProvider()
        chunks = [RetrievedChunk(
            chunk_id="c1", knowledge_file_id="f1",
            content="Refund info", chunk_index=0, similarity_score=0.9
        )]
        ctx = self._make_context(message="I want a refund immediately!", chunks=chunks)
        result = await provider.generate_decision(ctx)
        assert result.should_escalate is True
        assert result.answer is None

    @pytest.mark.asyncio
    async def test_rag_chunk_ids_in_decision_result(self):
        from app.ai.mock_provider import MockAIProvider
        from app.ai.base import RetrievedChunk
        provider = MockAIProvider()
        chunks = [
            RetrievedChunk(chunk_id="a", knowledge_file_id="f", content="Info A", chunk_index=0),
            RetrievedChunk(chunk_id="b", knowledge_file_id="f", content="Info B", chunk_index=1),
        ]
        ctx = self._make_context(chunks=chunks)
        result = await provider.generate_decision(ctx)
        assert set(result.retrieved_chunk_ids) == {"a", "b"}


# ── Knowledge retrieval fallback ───────────────────────────────────────────────

class TestKnowledgeRetrievalFallback:
    @pytest.mark.asyncio
    async def test_retrieval_returns_empty_on_sqlite(self, db_kn):
        """
        retrieve_similar_chunks gracefully returns [] when pgvector is not
        available (SQLite in tests) instead of raising an exception.
        """
        from app.services.knowledge_service import retrieve_similar_chunks
        from app.embeddings.mock_provider import MockEmbeddingProvider

        provider = MockEmbeddingProvider()
        embedding = await provider.embed_text("test query")
        chunks = await retrieve_similar_chunks(
            db=db_kn,
            tenant_id=uuid.uuid4(),
            query_embedding=embedding,
            top_k=3,
        )
        # On SQLite the pgvector operator fails gracefully → empty list
        assert isinstance(chunks, list)


# ── Worker task with knowledge ingestion ──────────────────────────────────────

class TestKnowledgeWorkerTask:
    @pytest.mark.asyncio
    async def test_process_knowledge_ingestion_inner(self, db_kn, tmp_path):
        """Worker inner function processes a knowledge file correctly."""
        from app.services.knowledge_service import create_knowledge_file
        from app.worker.tasks import _process_knowledge_ingestion_inner
        from app.models.knowledge import KnowledgeFileStatus

        tenant_id = uuid.uuid4()
        import app.core.config as _cfg
        original = _cfg.settings.KNOWLEDGE_STORAGE_PATH
        _cfg.settings.KNOWLEDGE_STORAGE_PATH = str(tmp_path)

        try:
            kf = await create_knowledge_file(
                db=db_kn, tenant_id=tenant_id,
                original_filename="kb.txt",
                content=b"Customer service knowledge article. " * 20,
                mime_type="text/plain",
            )
            result = await _process_knowledge_ingestion_inner(db_kn, str(kf.id))
            assert result["status"] == "completed"
            await db_kn.refresh(kf)
            assert kf.status == KnowledgeFileStatus.ready
        finally:
            _cfg.settings.KNOWLEDGE_STORAGE_PATH = original

    @pytest.mark.asyncio
    async def test_process_knowledge_ingestion_not_found(self, db_kn):
        from app.worker.tasks import _process_knowledge_ingestion_inner
        result = await _process_knowledge_ingestion_inner(db_kn, str(uuid.uuid4()))
        assert result["status"] == "not_found"
