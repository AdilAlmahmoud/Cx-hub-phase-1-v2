"""
Knowledge Base service — Phase 3.

Orchestrates:
  - File upload (save to disk, create DB record, enqueue ingestion)
  - Ingestion (extract text → chunk → embed → persist chunks)
  - Retrieval (embed query → pgvector similarity search → return top-k chunks)
  - Management (list, get, reindex)

All operations are strictly tenant-scoped.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Sequence

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.storage import save_upload, extract_text, chunk_text, delete_file
from app.models.knowledge import KnowledgeFile, KnowledgeChunk, KnowledgeFileStatus
from app.schemas.knowledge import KnowledgeChunkResult

logger = get_logger(__name__)


# ── CRUD helpers ──────────────────────────────────────────────────────────────

async def create_knowledge_file(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    original_filename: str,
    content: bytes,
    mime_type: Optional[str] = None,
) -> KnowledgeFile:
    """
    Save the uploaded file to disk and create a KnowledgeFile DB record
    with status=pending.  The caller is responsible for enqueueing ingestion.
    """
    file_path = save_upload(tenant_id, original_filename, content)

    kf = KnowledgeFile(
        tenant_id=tenant_id,
        original_filename=original_filename,
        file_path=file_path,
        file_size=len(content),
        mime_type=mime_type or "text/plain",
        status=KnowledgeFileStatus.pending,
        chunk_count=0,
    )
    db.add(kf)
    await db.commit()
    await db.refresh(kf)

    logger.info(
        "knowledge_file_uploaded",
        tenant_id=str(tenant_id),
        file_id=str(kf.id),
        filename=original_filename,
        size_bytes=len(content),
    )
    return kf


async def get_knowledge_file(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    file_id: uuid.UUID,
) -> Optional[KnowledgeFile]:
    """Return a KnowledgeFile scoped to the given tenant, or None."""
    result = await db.execute(
        select(KnowledgeFile).where(
            KnowledgeFile.id == file_id,
            KnowledgeFile.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def list_knowledge_files(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    status: Optional[KnowledgeFileStatus] = None,
    offset: int = 0,
    limit: int = 20,
) -> Sequence[KnowledgeFile]:
    """List knowledge files for a tenant with optional status filter."""
    stmt = select(KnowledgeFile).where(KnowledgeFile.tenant_id == tenant_id)
    if status is not None:
        stmt = stmt.where(KnowledgeFile.status == status)
    stmt = stmt.order_by(KnowledgeFile.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def reset_for_reindex(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    file_id: uuid.UUID,
) -> Optional[KnowledgeFile]:
    """
    Reset a knowledge file to pending so the worker re-ingests it.
    Returns the updated record, or None if not found.
    """
    kf = await get_knowledge_file(db, tenant_id, file_id)
    if kf is None:
        return None

    kf.status = KnowledgeFileStatus.pending
    kf.error_message = None
    await db.commit()
    await db.refresh(kf)

    logger.info(
        "knowledge_reindex_requested",
        tenant_id=str(tenant_id),
        file_id=str(file_id),
    )
    return kf


# ── Ingestion pipeline (called by worker) ─────────────────────────────────────

async def ingest_knowledge_file(db: AsyncSession, file_id: uuid.UUID) -> dict:
    """
    Full ingestion pipeline for a single knowledge file.

    1. Load file record
    2. Mark as ingesting
    3. Extract text from disk
    4. Chunk text
    5. Embed each chunk
    6. Delete old chunks (safe for reindex)
    7. Persist new chunks
    8. Mark as ready

    Returns a status dict suitable for the worker result.
    """
    result = await db.execute(
        select(KnowledgeFile).where(KnowledgeFile.id == file_id)
    )
    kf: Optional[KnowledgeFile] = result.scalar_one_or_none()

    if kf is None:
        logger.error("knowledge_ingestion_file_not_found", file_id=str(file_id))
        return {"status": "not_found", "file_id": str(file_id)}

    if kf.status == KnowledgeFileStatus.ready:
        logger.info("knowledge_ingestion_already_ready", file_id=str(file_id))
        return {"status": "skipped", "reason": "already_ready", "file_id": str(file_id)}

    # Mark ingesting
    kf.status = KnowledgeFileStatus.ingesting
    kf.error_message = None
    await db.commit()

    logger.info(
        "knowledge_ingestion_started",
        tenant_id=str(kf.tenant_id),
        file_id=str(kf.id),
        filename=kf.original_filename,
    )

    try:
        # Extract text
        text = extract_text(kf.file_path, kf.mime_type)
        if not text.strip():
            raise ValueError("Extracted text is empty — the document may have no readable content")

        # Chunk
        chunks = chunk_text(
            text,
            chunk_size=settings.KNOWLEDGE_CHUNK_SIZE,
            overlap=settings.KNOWLEDGE_CHUNK_OVERLAP,
        )
        if not chunks:
            raise ValueError("Chunking produced no content")

        # Embed
        from app.embeddings.openai_provider import get_embedding_provider
        embed_provider = get_embedding_provider()
        embeddings = await embed_provider.embed_batch(chunks)

        # Remove stale chunks from a previous ingestion run
        await db.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.knowledge_file_id == kf.id
            )
        )

        # Persist new chunks
        for i, (chunk_content, embedding) in enumerate(zip(chunks, embeddings)):
            chunk = KnowledgeChunk(
                tenant_id=kf.tenant_id,
                knowledge_file_id=kf.id,
                chunk_index=i,
                content=chunk_content,
                embedding=embedding,
                token_count=len(chunk_content.split()),
            )
            db.add(chunk)

        kf.status = KnowledgeFileStatus.ready
        kf.chunk_count = len(chunks)
        await db.commit()

        logger.info(
            "knowledge_ingestion_completed",
            tenant_id=str(kf.tenant_id),
            file_id=str(kf.id),
            filename=kf.original_filename,
            chunk_count=len(chunks),
        )
        return {
            "status": "completed",
            "file_id": str(file_id),
            "chunk_count": len(chunks),
        }

    except Exception as exc:
        kf.status = KnowledgeFileStatus.failed
        kf.error_message = str(exc)[:2000]
        await db.commit()

        logger.error(
            "knowledge_ingestion_failed",
            tenant_id=str(kf.tenant_id),
            file_id=str(kf.id),
            error=str(exc),
        )
        return {
            "status": "failed",
            "file_id": str(file_id),
            "error": str(exc),
        }


# ── RAG retrieval ─────────────────────────────────────────────────────────────

async def retrieve_similar_chunks(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    query_embedding: List[float],
    top_k: int = 3,
) -> List[KnowledgeChunkResult]:
    """
    Return the top-k knowledge chunks most similar to *query_embedding*,
    scoped to *tenant_id* and only from files with status='ready'.

    Uses pgvector's cosine distance operator (<=>).
    Returns an empty list when:
      - running against SQLite (tests)
      - pgvector extension is unavailable
      - no ready chunks exist for the tenant
    """
    # Format embedding as pgvector literal: [f1,f2,...,fN]
    embedding_literal = "[" + ",".join(f"{v:.8f}" for v in query_embedding) + "]"

    try:
        from sqlalchemy import text as sql_text

        stmt = sql_text("""
            SELECT
                kc.id,
                kc.knowledge_file_id,
                kc.content,
                kc.chunk_index,
                1 - (kc.embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM knowledge_chunks kc
            JOIN knowledge_files kf ON kf.id = kc.knowledge_file_id
            WHERE kc.tenant_id = :tenant_id
              AND kf.status = 'ready'
            ORDER BY kc.embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """)

        result = await db.execute(
            stmt,
            {
                "tenant_id": str(tenant_id),
                "embedding": embedding_literal,
                "top_k": top_k,
            },
        )
        rows = result.fetchall()

        chunks = [
            KnowledgeChunkResult(
                chunk_id=str(row[0]),
                knowledge_file_id=str(row[1]),
                content=row[2],
                chunk_index=row[3],
                similarity_score=float(row[4]),
            )
            for row in rows
        ]

        logger.info(
            "knowledge_retrieval",
            tenant_id=str(tenant_id),
            top_k=top_k,
            returned=len(chunks),
        )
        return chunks

    except Exception as exc:
        # Graceful degradation: if pgvector is unavailable (e.g. SQLite in tests)
        # log a warning and return empty — the AI job continues without RAG context.
        logger.warning(
            "knowledge_retrieval_failed",
            tenant_id=str(tenant_id),
            error=str(exc),
        )
        return []
