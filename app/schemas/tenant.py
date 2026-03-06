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


class TenantConfigCreate(TenantConfigBase):
    pass


class TenantConfigUpdate(BaseModel):
    ai_enabled: Optional[bool] = None
    auto_assign: Optional[bool] = None
    default_language: Optional[str] = None
    business_hours: Optional[dict] = None
    custom_settings: Optional[dict] = None


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
