import uuid
from typing import Optional, List, Tuple
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ticket import Ticket
from app.schemas.ticket import TicketCreate, TicketUpdate, TicketFilter


class TicketService:

    async def _next_ticket_number(self, db: AsyncSession, tenant_id: uuid.UUID) -> int:
        result = await db.execute(
            select(func.coalesce(func.max(Ticket.ticket_number), 0)).where(Ticket.tenant_id == tenant_id)
        )
        return result.scalar_one() + 1

    async def get_by_id(
        self, db: AsyncSession, ticket_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[Ticket]:
        result = await db.execute(
            select(Ticket).where(and_(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id))
        )
        return result.scalar_one_or_none()

    async def get_with_agent(
        self, db: AsyncSession, ticket_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[Ticket]:
        result = await db.execute(
            select(Ticket)
            .options(selectinload(Ticket.assigned_agent))
            .where(and_(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id))
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
        filters: Optional[TicketFilter] = None,
    ) -> Tuple[List[Ticket], int]:
        conditions = [Ticket.tenant_id == tenant_id]
        if filters:
            if filters.status:
                conditions.append(Ticket.status == filters.status)
            if filters.priority:
                conditions.append(Ticket.priority == filters.priority)
            if filters.assigned_agent_id:
                conditions.append(Ticket.assigned_agent_id == filters.assigned_agent_id)

        total = (
            await db.execute(select(func.count()).select_from(Ticket).where(*conditions))
        ).scalar_one()
        result = await db.execute(
            select(Ticket).where(*conditions).offset(skip).limit(limit).order_by(Ticket.created_at.desc())
        )
        return result.scalars().all(), total

    async def create(self, db: AsyncSession, tenant_id: uuid.UUID, data: TicketCreate) -> Ticket:
        ticket_number = await self._next_ticket_number(db, tenant_id)
        ticket = Ticket(tenant_id=tenant_id, ticket_number=ticket_number, **data.model_dump())
        db.add(ticket)
        await db.flush()
        return ticket

    async def update(self, db: AsyncSession, ticket: Ticket, data: TicketUpdate) -> Ticket:
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(ticket, field, value)
        await db.commit()
        await db.refresh(ticket)
        return ticket

    async def get_by_conversation(
        self, db: AsyncSession, conversation_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[Ticket]:
        result = await db.execute(
            select(Ticket).where(
                and_(Ticket.conversation_id == conversation_id, Ticket.tenant_id == tenant_id)
            )
        )
        return result.scalar_one_or_none()


ticket_service = TicketService()
