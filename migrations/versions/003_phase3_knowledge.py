"""Phase 3: Knowledge Base, pgvector, RAG

Revision ID: 003_phase3_knowledge
Revises: 002_phase2_ai_tables
Create Date: 2026-03-06 00:00:00.000000

Changes:
  - Enable pgvector PostgreSQL extension
  - Create knowledge_files table
  - Create knowledge_chunks table (with vector(1536) embedding column)
  - Add knowledge_enabled + retrieval_top_k to tenant_configs
  - Add retrieved_chunk_ids to ai_results
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003_phase3_knowledge"
down_revision: Union[str, None] = "002_phase2_ai_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enable pgvector extension ──────────────────────────────────────────────
    # Safe to run multiple times; ignored if already installed.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── knowledge_files ────────────────────────────────────────────────────────
    op.create_table(
        "knowledge_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_files_tenant_id", "knowledge_files", ["tenant_id"])
    op.create_index("ix_knowledge_files_status", "knowledge_files", ["status"])

    # ── knowledge_chunks ───────────────────────────────────────────────────────
    # embedding column uses pgvector's native 'vector' type (1536 dims,
    # matching OpenAI text-embedding-3-small and text-embedding-ada-002).
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # vector(1536) — pgvector type; created via raw DDL
        sa.Column("embedding", sa.Text(), nullable=True),  # placeholder, altered below
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("chunk_metadata", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["knowledge_file_id"], ["knowledge_files.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_chunks_tenant_id", "knowledge_chunks", ["tenant_id"])
    op.create_index("ix_knowledge_chunks_file_id", "knowledge_chunks", ["knowledge_file_id"])

    # Alter embedding column from TEXT to vector(1536)
    # This must be done after the table exists and pgvector extension is installed.
    op.execute(
        "ALTER TABLE knowledge_chunks "
        "ALTER COLUMN embedding TYPE vector(1536) "
        "USING NULL::vector(1536)"
    )

    # Add an IVFFlat index for approximate nearest-neighbour search.
    # lists=100 is a reasonable default for up to ~1M vectors per tenant.
    # cosine similarity is used via <=> operator.
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_embedding "
        "ON knowledge_chunks "
        "USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )

    # ── Extend tenant_configs with knowledge settings ──────────────────────────
    op.add_column(
        "tenant_configs",
        sa.Column("knowledge_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("retrieval_top_k", sa.Integer(), nullable=False, server_default="3"),
    )

    # ── Add RAG metadata column to ai_results ─────────────────────────────────
    op.add_column(
        "ai_results",
        sa.Column(
            "retrieved_chunk_ids",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_results", "retrieved_chunk_ids")
    op.drop_column("tenant_configs", "retrieval_top_k")
    op.drop_column("tenant_configs", "knowledge_enabled")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_files")
    op.execute("DROP EXTENSION IF EXISTS vector")
