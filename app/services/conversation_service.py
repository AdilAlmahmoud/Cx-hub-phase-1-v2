import uuid
from typing import Optional, List, Tuple
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation, ConversationStatus
from app.schemas.conversation import ConversationCreate, ConversationUpdate, ConversationFilter


class ConversationService:

    async def get_by_id(
        self, db: AsyncSession, conversation_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[Conversation]:
        result = await db.execute(
            select(Conversation).where(
                and_(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
            )
        )
        return result.scalar_one_or_none()

    async def get_with_customer(
        self, db: AsyncSession, conversation_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[Conversation]:
        result = await db.execute(
            select(Conversation)
            .options(selectinload(Conversation.customer))
            .where(and_(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id))
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
        filters: Optional[ConversationFilter] = None,
    ) -> Tuple[List[Conversation], int]:
        conditions = [Conversation.tenant_id == tenant_id]
        if filters:
            if filters.status:
                conditions.append(Conversation.status == filters.status)
            if filters.channel:
                conditions.append(Conversation.channel == filters.channel)
            if filters.customer_id:
                conditions.append(Conversation.customer_id == filters.customer_id)

        total = (
            await db.execute(select(func.count()).select_from(Conversation).where(*conditions))
        ).scalar_one()
        result = await db.execute(
            select(Conversation)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(Conversation.created_at.desc())
        )
        return result.scalars().all(), total

    async def get_open_for_customer(
        self, db: AsyncSession, customer_id: uuid.UUID, tenant_id: uuid.UUID, channel: str
    ) -> Optional[Conversation]:
        result = await db.execute(
            select(Conversation).where(
                and_(
                    Conversation.customer_id == customer_id,
                    Conversation.tenant_id == tenant_id,
                    Conversation.channel == channel,
                    Conversation.status == ConversationStatus.open,
                )
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self, db: AsyncSession, tenant_id: uuid.UUID, data: ConversationCreate
    ) -> Conversation:
        conversation = Conversation(tenant_id=tenant_id, **data.model_dump())
        db.add(conversation)
        await db.flush()
        return conversation

    async def update(
        self, db: AsyncSession, conversation: Conversation, data: ConversationUpdate
    ) -> Conversation:
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(conversation, field, value)
        await db.commit()
        await db.refresh(conversation)
        return conversation


conversation_service = ConversationService()
