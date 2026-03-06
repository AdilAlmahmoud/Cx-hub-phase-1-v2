"""
Settings API — Phase 4.

Organized settings endpoints for future frontend settings pages.
All settings are scoped to the current tenant and backed by TenantConfig.

Endpoints:
  GET  /settings           - Overview of all settings sections
  GET  /settings/ai        - AI/LLM settings
  PUT  /settings/ai        - Update AI/LLM settings
  GET  /settings/prompts   - Prompt template settings
  PUT  /settings/prompts   - Update prompt templates
  GET  /settings/channels  - Channel settings (enabled channels + ChannelConfig refs)
  GET  /settings/knowledge - Knowledge / RAG settings
  PUT  /settings/knowledge - Update knowledge settings
  GET  /settings/outbound  - Outbound messaging settings
  PUT  /settings/outbound  - Update outbound settings
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy import select

from app.api.deps import DB, CurrentTenant, OwnerOnly, CurrentUser
from app.core.logging import get_logger
from app.models.tenant import TenantConfig, ChannelConfig
from app.services.tenant_service import tenant_service

logger = get_logger(__name__)
router = APIRouter(prefix="/settings", tags=["Settings"])


# ── Pydantic schemas (settings-specific views of TenantConfig) ────────────────

class AISettingsResponse(BaseModel):
    ai_enabled: bool
    ai_provider: str  # from config (read-only env var)
    ai_model: str     # from config (read-only env var)
    ai_language: str
    ai_tone: str
    confidence_threshold: float
    auto_send_mode: str
    escalation_keywords: Optional[List[str]] = None
    handoff_message_template: Optional[str] = None
    ai_temperature: float
    ai_max_tokens: int

    model_config = {"from_attributes": True}


class AISettingsUpdate(BaseModel):
    ai_enabled: Optional[bool] = None
    ai_language: Optional[str] = None
    ai_tone: Optional[str] = None
    confidence_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    auto_send_mode: Optional[str] = None
    escalation_keywords: Optional[List[str]] = None
    handoff_message_template: Optional[str] = None
    ai_temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    ai_max_tokens: Optional[int] = Field(None, ge=100, le=8000)


class PromptSettingsResponse(BaseModel):
    system_prompt_template: Optional[str] = None
    reply_prompt_template: Optional[str] = None


class PromptSettingsUpdate(BaseModel):
    system_prompt_template: Optional[str] = Field(None, max_length=8000)
    reply_prompt_template: Optional[str] = Field(None, max_length=4000)


class KnowledgeSettingsResponse(BaseModel):
    knowledge_enabled: bool
    retrieval_top_k: int
    embedding_provider: str  # env-level read-only
    embedding_model: str     # env-level read-only
    chunk_size: int          # env-level read-only
    chunk_overlap: int       # env-level read-only


class KnowledgeSettingsUpdate(BaseModel):
    knowledge_enabled: Optional[bool] = None
    retrieval_top_k: Optional[int] = Field(None, ge=1, le=20)


class OutboundSettingsResponse(BaseModel):
    outbound_enabled: bool
    outbound_provider: str
    email_from_address: Optional[str] = None
    email_from_name: Optional[str] = None
    rate_limit_enabled: bool
    max_messages_per_hour: int


class OutboundSettingsUpdate(BaseModel):
    outbound_enabled: Optional[bool] = None
    outbound_provider: Optional[str] = None
    email_from_address: Optional[str] = Field(None, max_length=255)
    email_from_name: Optional[str] = Field(None, max_length=255)
    rate_limit_enabled: Optional[bool] = None
    max_messages_per_hour: Optional[int] = Field(None, ge=1, le=10000)


class ChannelSettingsItem(BaseModel):
    channel: str
    is_enabled: bool
    # provider_config is intentionally excluded to avoid leaking secrets


class ChannelSettingsResponse(BaseModel):
    channels: List[ChannelSettingsItem]
    supported_channels: List[str] = ["whatsapp", "webchat", "sms", "email"]


class SettingsOverview(BaseModel):
    tenant_id: str
    ai_enabled: bool
    knowledge_enabled: bool
    outbound_enabled: bool
    active_channels: List[str]
    ai_provider: str
    embedding_provider: str
    outbound_provider: str


# ── Helper: load TenantConfig ─────────────────────────────────────────────────

async def _get_config(db, tenant_id) -> TenantConfig:
    result = await db.execute(
        select(TenantConfig).where(TenantConfig.tenant_id == tenant_id)
    )
    cfg = result.scalar_one_or_none()
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant configuration not found",
        )
    return cfg


async def _update_config_fields(db, tenant_id, updates: dict) -> TenantConfig:
    cfg = await _get_config(db, tenant_id)
    for field, value in updates.items():
        if value is not None:
            setattr(cfg, field, value)
    await db.commit()
    await db.refresh(cfg)
    return cfg


# ── Overview ──────────────────────────────────────────────────────────────────

@router.get("", response_model=SettingsOverview)
async def get_settings_overview(
    db: DB,
    current_tenant: CurrentTenant,
    _user: CurrentUser,
):
    """Return a high-level summary of all settings categories."""
    from app.core.config import settings as app_settings
    cfg = await _get_config(db, current_tenant.id)

    channel_configs = (
        await db.execute(
            select(ChannelConfig).where(
                ChannelConfig.tenant_id == current_tenant.id,
                ChannelConfig.is_enabled == True,
            )
        )
    ).scalars().all()
    active_channels = [c.channel for c in channel_configs]

    return SettingsOverview(
        tenant_id=str(current_tenant.id),
        ai_enabled=cfg.ai_enabled,
        knowledge_enabled=cfg.knowledge_enabled,
        outbound_enabled=getattr(cfg, "outbound_enabled", False),
        active_channels=active_channels,
        ai_provider=app_settings.AI_PROVIDER,
        embedding_provider=app_settings.EMBEDDING_PROVIDER,
        outbound_provider=getattr(cfg, "outbound_provider", "mock"),
    )


# ── AI Settings ───────────────────────────────────────────────────────────────

@router.get("/ai", response_model=AISettingsResponse)
async def get_ai_settings(db: DB, current_tenant: CurrentTenant, _user: CurrentUser):
    """Get AI/LLM settings for the current tenant."""
    from app.core.config import settings as app_settings
    cfg = await _get_config(db, current_tenant.id)
    return AISettingsResponse(
        ai_enabled=cfg.ai_enabled,
        ai_provider=app_settings.AI_PROVIDER,
        ai_model=app_settings.OPENAI_MODEL,
        ai_language=cfg.ai_language,
        ai_tone=cfg.ai_tone,
        confidence_threshold=cfg.confidence_threshold,
        auto_send_mode=cfg.auto_send_mode,
        escalation_keywords=cfg.escalation_keywords,
        handoff_message_template=cfg.handoff_message_template,
        ai_temperature=getattr(cfg, "ai_temperature", 0.2),
        ai_max_tokens=getattr(cfg, "ai_max_tokens", 500),
    )


@router.put("/ai", response_model=AISettingsResponse)
async def update_ai_settings(body: AISettingsUpdate, db: DB, current_tenant: CurrentTenant, _user: OwnerOnly):
    """Update AI/LLM settings for the current tenant."""
    from app.core.config import settings as app_settings
    updates = body.model_dump(exclude_none=True)
    cfg = await _update_config_fields(db, current_tenant.id, updates)
    return AISettingsResponse(
        ai_enabled=cfg.ai_enabled,
        ai_provider=app_settings.AI_PROVIDER,
        ai_model=app_settings.OPENAI_MODEL,
        ai_language=cfg.ai_language,
        ai_tone=cfg.ai_tone,
        confidence_threshold=cfg.confidence_threshold,
        auto_send_mode=cfg.auto_send_mode,
        escalation_keywords=cfg.escalation_keywords,
        handoff_message_template=cfg.handoff_message_template,
        ai_temperature=getattr(cfg, "ai_temperature", 0.2),
        ai_max_tokens=getattr(cfg, "ai_max_tokens", 500),
    )


# ── Prompt Templates ──────────────────────────────────────────────────────────

@router.get("/prompts", response_model=PromptSettingsResponse)
async def get_prompt_settings(db: DB, current_tenant: CurrentTenant, _user: OwnerOnly):
    """Get prompt template settings (owner only — contains sensitive config)."""
    cfg = await _get_config(db, current_tenant.id)
    return PromptSettingsResponse(
        system_prompt_template=getattr(cfg, "system_prompt_template", None),
        reply_prompt_template=getattr(cfg, "reply_prompt_template", None),
    )


@router.put("/prompts", response_model=PromptSettingsResponse)
async def update_prompt_settings(
    body: PromptSettingsUpdate, db: DB, current_tenant: CurrentTenant, _user: OwnerOnly
):
    """Update prompt templates. Null values clear the template (revert to built-in default)."""
    cfg = await _get_config(db, current_tenant.id)
    # Allow explicit None to clear templates (don't use exclude_none here)
    if body.system_prompt_template is not None or "system_prompt_template" in body.model_fields_set:
        cfg.system_prompt_template = body.system_prompt_template
    if body.reply_prompt_template is not None or "reply_prompt_template" in body.model_fields_set:
        cfg.reply_prompt_template = body.reply_prompt_template
    await db.commit()
    await db.refresh(cfg)
    return PromptSettingsResponse(
        system_prompt_template=cfg.system_prompt_template,
        reply_prompt_template=cfg.reply_prompt_template,
    )


# ── Knowledge Settings ────────────────────────────────────────────────────────

@router.get("/knowledge", response_model=KnowledgeSettingsResponse)
async def get_knowledge_settings(db: DB, current_tenant: CurrentTenant, _user: CurrentUser):
    """Get knowledge base / RAG settings."""
    from app.core.config import settings as app_settings
    cfg = await _get_config(db, current_tenant.id)
    return KnowledgeSettingsResponse(
        knowledge_enabled=cfg.knowledge_enabled,
        retrieval_top_k=cfg.retrieval_top_k,
        embedding_provider=app_settings.EMBEDDING_PROVIDER,
        embedding_model=app_settings.OPENAI_EMBEDDING_MODEL,
        chunk_size=app_settings.KNOWLEDGE_CHUNK_SIZE,
        chunk_overlap=app_settings.KNOWLEDGE_CHUNK_OVERLAP,
    )


@router.put("/knowledge", response_model=KnowledgeSettingsResponse)
async def update_knowledge_settings(
    body: KnowledgeSettingsUpdate, db: DB, current_tenant: CurrentTenant, _user: OwnerOnly
):
    """Update knowledge base / RAG settings."""
    from app.core.config import settings as app_settings
    updates = body.model_dump(exclude_none=True)
    cfg = await _update_config_fields(db, current_tenant.id, updates)
    return KnowledgeSettingsResponse(
        knowledge_enabled=cfg.knowledge_enabled,
        retrieval_top_k=cfg.retrieval_top_k,
        embedding_provider=app_settings.EMBEDDING_PROVIDER,
        embedding_model=app_settings.OPENAI_EMBEDDING_MODEL,
        chunk_size=app_settings.KNOWLEDGE_CHUNK_SIZE,
        chunk_overlap=app_settings.KNOWLEDGE_CHUNK_OVERLAP,
    )


# ── Outbound Settings ─────────────────────────────────────────────────────────

@router.get("/outbound", response_model=OutboundSettingsResponse)
async def get_outbound_settings(db: DB, current_tenant: CurrentTenant, _user: CurrentUser):
    """Get outbound messaging settings."""
    cfg = await _get_config(db, current_tenant.id)
    return OutboundSettingsResponse(
        outbound_enabled=getattr(cfg, "outbound_enabled", False),
        outbound_provider=getattr(cfg, "outbound_provider", "mock"),
        email_from_address=getattr(cfg, "email_from_address", None),
        email_from_name=getattr(cfg, "email_from_name", None),
        rate_limit_enabled=getattr(cfg, "rate_limit_enabled", False),
        max_messages_per_hour=getattr(cfg, "max_messages_per_hour", 100),
    )


@router.put("/outbound", response_model=OutboundSettingsResponse)
async def update_outbound_settings(
    body: OutboundSettingsUpdate, db: DB, current_tenant: CurrentTenant, _user: OwnerOnly
):
    """Update outbound messaging settings."""
    updates = body.model_dump(exclude_none=True)
    cfg = await _update_config_fields(db, current_tenant.id, updates)
    return OutboundSettingsResponse(
        outbound_enabled=getattr(cfg, "outbound_enabled", False),
        outbound_provider=getattr(cfg, "outbound_provider", "mock"),
        email_from_address=getattr(cfg, "email_from_address", None),
        email_from_name=getattr(cfg, "email_from_name", None),
        rate_limit_enabled=getattr(cfg, "rate_limit_enabled", False),
        max_messages_per_hour=getattr(cfg, "max_messages_per_hour", 100),
    )


# ── Channel Settings ──────────────────────────────────────────────────────────

@router.get("/channels", response_model=ChannelSettingsResponse)
async def get_channel_settings(db: DB, current_tenant: CurrentTenant, _user: CurrentUser):
    """
    Get channel configuration overview (enabled/disabled state only).
    Provider credentials are NOT included in the response.
    """
    configs = (
        await db.execute(
            select(ChannelConfig).where(ChannelConfig.tenant_id == current_tenant.id)
        )
    ).scalars().all()

    return ChannelSettingsResponse(
        channels=[
            ChannelSettingsItem(channel=c.channel, is_enabled=c.is_enabled)
            for c in configs
        ]
    )
