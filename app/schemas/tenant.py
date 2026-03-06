import uuid
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class TenantConfigBase(BaseModel):
    ai_enabled: bool = False
    auto_assign: bool = True
    default_language: str = "en"
    business_hours: Optional[dict] = None
    custom_settings: Optional[dict] = None

    # ── Phase 2: AI policy ────────────────────────────────────────────────────
    ai_language: str = "en"
    ai_tone: str = "professional"
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    # "off" | "supervised" | "auto"
    auto_send_mode: str = "off"
    escalation_keywords: Optional[List[str]] = None
    handoff_message_template: Optional[str] = None

    # ── Phase 3: Knowledge Base / RAG ─────────────────────────────────────────
    knowledge_enabled: bool = False
    retrieval_top_k: int = Field(default=3, ge=1, le=20)


class TenantConfigCreate(TenantConfigBase):
    pass


class TenantConfigUpdate(BaseModel):
    ai_enabled: Optional[bool] = None
    auto_assign: Optional[bool] = None
    default_language: Optional[str] = None
    business_hours: Optional[dict] = None
    custom_settings: Optional[dict] = None

    # ── Phase 2: AI policy ────────────────────────────────────────────────────
    ai_language: Optional[str] = None
    ai_tone: Optional[str] = None
    confidence_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    auto_send_mode: Optional[str] = None
    escalation_keywords: Optional[List[str]] = None
    handoff_message_template: Optional[str] = None

    # ── Phase 3: Knowledge Base / RAG ─────────────────────────────────────────
    knowledge_enabled: Optional[bool] = None
    retrieval_top_k: Optional[int] = Field(default=None, ge=1, le=20)


class TenantConfigResponse(TenantConfigBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChannelConfigBase(BaseModel):
    channel: str
    is_enabled: bool = True
    provider_config: Optional[dict] = None


class ChannelConfigCreate(ChannelConfigBase):
    webhook_secret: Optional[str] = None


class ChannelConfigUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    webhook_secret: Optional[str] = None
    provider_config: Optional[dict] = None


class ChannelConfigResponse(ChannelConfigBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TenantBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    contact_email: Optional[EmailStr] = None
    plan: str = "starter"


class TenantCreate(TenantBase):
    pass


class TenantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    contact_email: Optional[EmailStr] = None
    plan: Optional[str] = None
    is_active: Optional[bool] = None


class TenantResponse(TenantBase):
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TenantDetailResponse(TenantResponse):
    config: Optional[TenantConfigResponse] = None
    channel_configs: List[ChannelConfigResponse] = []
