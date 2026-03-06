import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class CustomerBase(BaseModel):
    external_id: str = Field(..., min_length=1, max_length=255)
    channel: str
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    metadata_: Optional[dict] = None


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    metadata_: Optional[dict] = None


class CustomerResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    external_id: str
    channel: str
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    metadata_: Optional[dict]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
