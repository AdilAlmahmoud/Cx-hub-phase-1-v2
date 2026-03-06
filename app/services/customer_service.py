import uuid
from typing import Optional, List, Tuple
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.schemas.customer import CustomerCreate, CustomerUpdate


class CustomerService:

    async def get_by_id(self, db: AsyncSession, customer_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[Customer]:
        result = await db.execute(
            select(Customer).where(and_(Customer.id == customer_id, Customer.tenant_id == tenant_id))
        )
        return result.scalar_one_or_none()

    async def get_by_external_id(
        self, db: AsyncSession, external_id: str, tenant_id: uuid.UUID
    ) -> Optional[Customer]:
        result = await db.execute(
            select(Customer).where(
                and_(Customer.external_id == external_id, Customer.tenant_id == tenant_id)
            )
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
        channel: Optional[str] = None,
    ) -> Tuple[List[Customer], int]:
        filters = [Customer.tenant_id == tenant_id]
        if channel:
            filters.append(Customer.channel == channel)
        total = (
            await db.execute(select(func.count()).select_from(Customer).where(*filters))
        ).scalar_one()
        result = await db.execute(
            select(Customer).where(*filters).offset(skip).limit(limit).order_by(Customer.created_at.desc())
        )
        return result.scalars().all(), total

    async def get_or_create(
        self, db: AsyncSession, tenant_id: uuid.UUID, external_id: str, channel: str, **kwargs
    ) -> Tuple[Customer, bool]:
        """Get existing or create new customer. Returns (customer, created)."""
        customer = await self.get_by_external_id(db, external_id, tenant_id)
        if customer:
            return customer, False
        customer = Customer(tenant_id=tenant_id, external_id=external_id, channel=channel, **kwargs)
        db.add(customer)
        await db.flush()
        return customer, True

    async def create(self, db: AsyncSession, tenant_id: uuid.UUID, data: CustomerCreate) -> Customer:
        customer = Customer(tenant_id=tenant_id, **data.model_dump())
        db.add(customer)
        await db.commit()
        await db.refresh(customer)
        return customer

    async def update(self, db: AsyncSession, customer: Customer, data: CustomerUpdate) -> Customer:
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(customer, field, value)
        await db.commit()
        await db.refresh(customer)
        return customer


customer_service = CustomerService()
