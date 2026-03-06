import uuid
from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DB, CurrentUser, CurrentTenant, OwnerOnly
from app.schemas.tenant import (
    TenantCreate, TenantUpdate, TenantResponse, TenantDetailResponse,
    TenantConfigUpdate, TenantConfigResponse,
    ChannelConfigCreate, ChannelConfigResponse,
)
from app.schemas.common import PaginatedResponse
from app.services.tenant_service import tenant_service

router = APIRouter(prefix="/tenants", tags=["Tenants"])


@router.get("", response_model=PaginatedResponse[TenantResponse])
async def list_tenants(
    db: DB,
    _: OwnerOnly,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_active: bool | None = Query(None),
):
    """List all tenants (owner-only, intended for super-admin use)."""
    tenants, total = await tenant_service.get_all(
        db, skip=(page - 1) * page_size, limit=page_size, is_active=is_active
    )
    return PaginatedResponse.create(
        items=[TenantResponse.model_validate(t) for t in tenants],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(body: TenantCreate, db: DB, _: OwnerOnly):
    """Create a new tenant."""
    tenant = await tenant_service.create(db, body)
    return TenantResponse.model_validate(tenant)


@router.get("/me", response_model=TenantDetailResponse)
async def get_my_tenant(db: DB, current_tenant: CurrentTenant, _: CurrentUser):
    """Get current user's tenant with full details."""
    tenant = await tenant_service.get_with_details(db, current_tenant.id)
    return TenantDetailResponse.model_validate(tenant)


@router.get("/{tenant_id}", response_model=TenantDetailResponse)
async def get_tenant(tenant_id: uuid.UUID, db: DB, _: OwnerOnly):
    """Get a tenant by ID."""
    tenant = await tenant_service.get_with_details(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return TenantDetailResponse.model_validate(tenant)


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(tenant_id: uuid.UUID, body: TenantUpdate, db: DB, _: OwnerOnly):
    """Update a tenant."""
    tenant = await tenant_service.get_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    tenant = await tenant_service.update(db, tenant, body)
    return TenantResponse.model_validate(tenant)


@router.put("/me/config", response_model=TenantConfigResponse)
async def update_my_tenant_config(
    body: TenantConfigUpdate, db: DB, current_tenant: CurrentTenant, _: OwnerOnly
):
    """Update the current tenant's configuration."""
    config = await tenant_service.update_config(db, current_tenant.id, body)
    return TenantConfigResponse.model_validate(config)


@router.put("/me/channels/{channel}", response_model=ChannelConfigResponse)
async def upsert_channel_config(
    channel: str, body: ChannelConfigCreate, db: DB, current_tenant: CurrentTenant, _: OwnerOnly
):
    """Configure a channel for the current tenant."""
    body.channel = channel
    config = await tenant_service.upsert_channel_config(db, current_tenant.id, body)
    return ChannelConfigResponse.model_validate(config)


@router.get("/me/channels", response_model=list[ChannelConfigResponse])
async def list_channel_configs(db: DB, current_tenant: CurrentTenant, _: CurrentUser):
    """List all channel configurations for the current tenant."""
    configs = await tenant_service.get_channel_configs(db, current_tenant.id)
    return [ChannelConfigResponse.model_validate(c) for c in configs]
