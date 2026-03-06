"""
Knowledge Base models — Phase 3.

KnowledgeFile  — tracks an uploaded document (status lifecycle: pending → ingesting → ready | failed)
KnowledgeChunk — one text chunk of a file + its embedding vector

All rows are scoped to a tenant_id.  The embedding column uses pgvector's
Vector type which serialises as "[f1,f2,...]" text and is stored as the
native 'vector' type in PostgreSQL (or as TEXT in SQLite for unit tests).
"""
import uuid
from enum import Enum
from typing import Optional, List

from sqlalchemy import String, Text, Integer, ForeignKey, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

# pgvector SQLAlchemy integration — graceful fallback to JSON for SQLite tests
try:
    from pgvector.sqlalchemy import Vector as _VectorType
    _VECTOR_COL = _VectorType(1536)
except ImportError:
    _VECTOR_COL = JSON  # type: ignore[assignment]


class KnowledgeFileStatus(str, Enum):
    pending = "pending"
    ingesting = "ingesting"
    ready = "ready"
    failed = "failed"


class KnowledgeFile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Tracks a single uploaded knowledge document.

    Lifecycle:
      pending   — file saved to disk, ingestion not yet started
      ingesting — worker is actively chunking + embedding
      ready     — all chunks persisted; file is searchable
      failed    — ingestion encountered an unrecoverable error
    """
    __tablename__ = "knowledge_files"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Original name shown to the user
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    # Name / path on disk (content-hash based to avoid collisions)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # bytes
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    status: Mapped[KnowledgeFileStatus] = mapped_column(
        String(20), nullable=False, default=KnowledgeFileStatus.pending,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    chunks: Mapped[List["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk", back_populates="knowledge_file", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<KnowledgeFile id={self.id} status={self.status} file={self.original_filename}>"


class KnowledgeChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A single text chunk from a KnowledgeFile with its embedding vector.

    chunk_index — 0-based position within the source file.
    embedding   — Vector(1536) in PostgreSQL; TEXT-backed list in SQLite tests.
    """
    __tablename__ = "knowledge_chunks"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    knowledge_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_files.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Vector column: pgvector in PostgreSQL, JSON fallback in SQLite for tests.
    # The type is resolved at import time (see top of module).
    embedding: Mapped[Optional[list]] = mapped_column(_VECTOR_COL, nullable=True)

    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Optional per-chunk metadata (e.g. page_number, section_title)
    metadata_: Mapped[Optional[dict]] = mapped_column("chunk_metadata", JSON, nullable=True)

    # Relationship
    knowledge_file: Mapped["KnowledgeFile"] = relationship(
        "KnowledgeFile", back_populates="chunks",
    )

    def __repr__(self) -> str:
        return (
            f"<KnowledgeChunk id={self.id} "
            f"file={self.knowledge_file_id} idx={self.chunk_index}>"
        )
