"""Phase 4: Outbound Messaging, Email Channel, Settings Hardening

Revision ID: 004_phase4_outbound
Revises: 003_phase3_knowledge
Create Date: 2026-03-06 00:00:00.000000

Changes:
  - Create outbound_messages table
  - Create outbound_attempts table
  - Add Phase 4 TenantConfig columns:
      system_prompt_template, reply_prompt_template,
      ai_temperature, ai_max_tokens,
      outbound_enabled, outbound_provider,
      email_from_address, email_from_name,
      rate_limit_enabled, max_messages_per_hour
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004_phase4_outbound"
down_revision: Union[str, None] = "003_phase3_knowledge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── outbound_messages ──────────────────────────────────────────────────────
    op.create_table(
        "outbound_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ai_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sent_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("recipient_identifier", sa.String(500), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("message_type", sa.String(50), nullable=False, server_default="text"),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("is_ai_generated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("extra_metadata", postgresql.JSON(astext_type=sa.Text()), nullable=True),
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
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ai_result_id"], ["ai_results.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sent_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbound_messages_tenant_id", "outbound_messages", ["tenant_id"])
    op.create_index("ix_outbound_messages_conversation_id", "outbound_messages", ["conversation_id"])
    op.create_index("ix_outbound_messages_ticket_id", "outbound_messages", ["ticket_id"])
    op.create_index("ix_outbound_messages_status", "outbound_messages", ["status"])
    op.create_index("ix_outbound_messages_channel", "outbound_messages", ["channel"])

    # ── outbound_attempts ──────────────────────────────────────────────────────
    op.create_table(
        "outbound_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outbound_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False, server_default="mock"),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("raw_response", postgresql.JSON(astext_type=sa.Text()), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["outbound_message_id"], ["outbound_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbound_attempts_message_id", "outbound_attempts", ["outbound_message_id"])
    op.create_index("ix_outbound_attempts_tenant_id", "outbound_attempts", ["tenant_id"])

    # ── Phase 4: TenantConfig additions ───────────────────────────────────────
    op.add_column("tenant_configs", sa.Column("system_prompt_template", sa.Text(), nullable=True))
    op.add_column("tenant_configs", sa.Column("reply_prompt_template", sa.Text(), nullable=True))
    op.add_column(
        "tenant_configs",
        sa.Column("ai_temperature", sa.Float(), nullable=False, server_default="0.2"),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("ai_max_tokens", sa.Integer(), nullable=False, server_default="500"),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("outbound_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("outbound_provider", sa.String(50), nullable=False, server_default="mock"),
    )
    op.add_column("tenant_configs", sa.Column("email_from_address", sa.String(255), nullable=True))
    op.add_column("tenant_configs", sa.Column("email_from_name", sa.String(255), nullable=True))
    op.add_column(
        "tenant_configs",
        sa.Column("rate_limit_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("max_messages_per_hour", sa.Integer(), nullable=False, server_default="100"),
    )


def downgrade() -> None:
    # Remove TenantConfig columns
    for col in [
        "max_messages_per_hour", "rate_limit_enabled",
        "email_from_name", "email_from_address",
        "outbound_provider", "outbound_enabled",
        "ai_max_tokens", "ai_temperature",
        "reply_prompt_template", "system_prompt_template",
    ]:
        op.drop_column("tenant_configs", col)

    op.drop_table("outbound_attempts")
    op.drop_table("outbound_messages")
