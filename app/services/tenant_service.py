import uuid
from typing import Optional, List, Tuple
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tenant import Tenant, TenantConfig, ChannelConfig
from app.schemas.tenant import TenantCreate, TenantUpdate, TenantConfigCreate, TenantConfigUpdate, ChannelConfigCreate, ChannelConfigUpdate
from fastapi import HTTPException, status


class TenantService:

    async def get_by_id(self, db: AsyncSession, tenant_id: uuid.UUID) -> Optional[Tenant]:
        result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one_or_none()

    async def get_by_slug(self, db: AsyncSession, slug: str) -> Optional[Tenant]:
        result = await db.execute(select(Tenant).where(Tenant.slug == slug))
        return result.scalar_one_or_none()

    async def get_all(
        self, db: AsyncSession, skip: int = 0, limit: int = 20, is_active: Optional[bool] = None
    ) -> Tuple[List[Tenant], int]:
        query = select(Tenant)
        count_query = select(func.count()).select_from(Tenant)
        if is_active is not None:
            query = query.where(Tenant.is_active == is_active)
            count_query = count_query.where(Tenant.is_active == is_active)
        total = (await db.execute(count_query)).scalar_one()
        result = await db.execute(query.offset(skip).limit(limit).order_by(Tenant.created_at.desc()))
        return result.scalars().all(), total

    async def create(self, db: AsyncSession, data: TenantCreate) -> Tenant:
        existing = await self.get_by_slug(db, data.slug)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tenant slug already exists")
        tenant = Tenant(**data.model_dump())
        db.add(tenant)
        await db.flush()
        # Create default config
        config = TenantConfig(tenant_id=tenant.id)
        db.add(config)
        await db.commit()
        await db.refresh(tenant)
        return tenant

    async def update(self, db: AsyncSession, tenant: Tenant, data: TenantUpdate) -> Tenant:
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(tenant, field, value)
        await db.commit()
        await db.refresh(tenant)
        return tenant

    async def get_with_details(self, db: AsyncSession, tenant_id: uuid.UUID) -> Optional[Tenant]:
        result = await db.execute(
            select(Tenant)
            .options(selectinload(Tenant.config), selectinload(Tenant.channel_configs))
            .where(Tenant.id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def update_config(
        self, db: AsyncSession, tenant_id: uuid.UUID, data: TenantConfigUpdate
    ) -> TenantConfig:
        result = await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
        config = result.scalar_one_or_none()
        if not config:
            config = TenantConfig(tenant_id=tenant_id)
            db.add(config)
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(config, field, value)
        await db.commit()
        await db.refresh(config)
        return config

    async def upsert_channel_config(
        self, db: AsyncSession, tenant_id: uuid.UUID, data: ChannelConfigCreate
    ) -> ChannelConfig:
        result = await db.execute(
            select(ChannelConfig).where(
                ChannelConfig.tenant_id == tenant_id,
                ChannelConfig.channel == data.channel,
            )
        )
        channel_config = result.scalar_one_or_none()
        if channel_config:
            for field, value in data.model_dump(exclude_none=True).items():
                setattr(channel_config, field, value)
        else:
            channel_config = ChannelConfig(tenant_id=tenant_id, **data.model_dump())
            db.add(channel_config)
        await db.commit()
        await db.refresh(channel_config)
        return channel_config

    async def get_channel_configs(self, db: AsyncSession, tenant_id: uuid.UUID) -> List[ChannelConfig]:
        result = await db.execute(
            select(ChannelConfig).where(ChannelConfig.tenant_id == tenant_id)
        )
        return result.scalars().all()


tenant_service = TenantService()
