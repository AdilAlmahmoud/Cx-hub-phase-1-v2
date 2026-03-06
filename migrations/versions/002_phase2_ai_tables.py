"""Phase 2: AI tables and tenant config AI policy columns

Revision ID: 002_phase2_ai_tables
Revises: 001_initial_schema
Create Date: 2026-03-06 00:00:00.000000

Changes:
  - Add AI policy columns to tenant_configs
  - Create ai_jobs table
  - Create ai_results table
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002_phase2_ai_tables"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Extend tenant_configs with AI policy columns ───────────────────────────
    op.add_column(
        "tenant_configs",
        sa.Column("ai_language", sa.String(10), nullable=False, server_default="en"),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("ai_tone", sa.String(50), nullable=False, server_default="professional"),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("confidence_threshold", sa.Float(), nullable=False, server_default="0.7"),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("auto_send_mode", sa.String(20), nullable=False, server_default="off"),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("escalation_keywords", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("handoff_message_template", sa.Text(), nullable=True),
    )

    # ── ai_jobs ────────────────────────────────────────────────────────────────
    op.create_table(
        "ai_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_log_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "processing", "completed", "failed", name="aijobstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_log_id"], ["event_logs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_jobs_tenant_id", "ai_jobs", ["tenant_id"])
    op.create_index("ix_ai_jobs_ticket_id", "ai_jobs", ["ticket_id"])
    op.create_index("ix_ai_jobs_status", "ai_jobs", ["status"])

    # ── ai_results ────────────────────────────────────────────────────────────
    op.create_table(
        "ai_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ai_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("intent", sa.String(255), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("should_escalate", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("risk_flags", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("escalation_reason", sa.Text(), nullable=True),
        sa.Column("safe_to_auto_send", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("processing_notes", sa.Text(), nullable=True),
        sa.Column("provider_name", sa.String(100), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=True),
        sa.Column("processing_duration_ms", sa.Integer(), nullable=True),
        sa.Column("raw_provider_response", postgresql.JSON(astext_type=sa.Text()), nullable=True),
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
        sa.ForeignKeyConstraint(["ai_job_id"], ["ai_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ai_job_id", name="uq_ai_result_job"),
    )
    op.create_index("ix_ai_results_tenant_id", "ai_results", ["tenant_id"])
    op.create_index("ix_ai_results_ticket_id", "ai_results", ["ticket_id"])


def downgrade() -> None:
    op.drop_table("ai_results")
    op.drop_table("ai_jobs")
    op.execute("DROP TYPE IF EXISTS aijobstatus")

    op.drop_column("tenant_configs", "handoff_message_template")
    op.drop_column("tenant_configs", "escalation_keywords")
    op.drop_column("tenant_configs", "auto_send_mode")
    op.drop_column("tenant_configs", "confidence_threshold")
    op.drop_column("tenant_configs", "ai_tone")
    op.drop_column("tenant_configs", "ai_language")
