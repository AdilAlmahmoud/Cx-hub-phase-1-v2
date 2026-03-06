"""
Seed script — creates a demo tenant with owner + agent users
and sample channel configs.

Usage:
    python -m scripts.seed
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.core.config import settings
from app.core.security import hash_password
from app.models.tenant import Tenant, TenantConfig, ChannelConfig
from app.models.user import User, UserRole


DEMO_TENANT_SLUG = "demo-corp"
DEMO_OWNER_EMAIL = "owner@demo-corp.com"
DEMO_OWNER_PASSWORD = "DemoPass123!"
DEMO_AGENT_EMAIL = "agent@demo-corp.com"
DEMO_AGENT_PASSWORD = "AgentPass123!"


async def seed():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    AsyncSession_ = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSession_() as db:
        # Check if already seeded
        from sqlalchemy import select
        result = await db.execute(select(Tenant).where(Tenant.slug == DEMO_TENANT_SLUG))
        existing = result.scalar_one_or_none()
        if existing:
            print(f"[seed] Demo tenant '{DEMO_TENANT_SLUG}' already exists — skipping.")
            return

        # Create tenant
        tenant = Tenant(
            name="Demo Corp",
            slug=DEMO_TENANT_SLUG,
            contact_email="hello@demo-corp.com",
            plan="starter",
            is_active=True,
        )
        db.add(tenant)
        await db.flush()

        # Tenant config
        config = TenantConfig(
            tenant_id=tenant.id,
            ai_enabled=False,
            auto_assign=True,
            default_language="en",
        )
        db.add(config)

        # Channel configs
        for channel in ["whatsapp", "webchat", "sms"]:
            db.add(ChannelConfig(tenant_id=tenant.id, channel=channel, is_enabled=True))

        # Owner user
        owner = User(
            tenant_id=tenant.id,
            email=DEMO_OWNER_EMAIL,
            full_name="Demo Owner",
            role=UserRole.owner,
            hashed_password=hash_password(DEMO_OWNER_PASSWORD),
            is_active=True,
        )
        db.add(owner)

        # Agent user
        agent = User(
            tenant_id=tenant.id,
            email=DEMO_AGENT_EMAIL,
            full_name="Demo Agent",
            role=UserRole.agent,
            hashed_password=hash_password(DEMO_AGENT_PASSWORD),
            is_active=True,
        )
        db.add(agent)

        await db.commit()

    print(f"""
[seed] Demo tenant created successfully!
  Tenant slug : {DEMO_TENANT_SLUG}
  Owner login : {DEMO_OWNER_EMAIL}  /  {DEMO_OWNER_PASSWORD}
  Agent login : {DEMO_AGENT_EMAIL}  /  {DEMO_AGENT_PASSWORD}
  Channels    : whatsapp, webchat, sms
""")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
