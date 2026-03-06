"""
Inbound Message Processing Service.

Orchestrates the full pipeline when a channel adapter produces a UnifiedEvent:
  1. Resolve or create Customer
  2. Resolve or create Conversation
  3. Create or update Ticket
  4. Persist EventLog
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import UnifiedEvent
from app.models.conversation import ConversationStatus
from app.models.ticket import TicketStatus, TicketPriority
from app.models.event_log import EventLog
from app.schemas.conversation import ConversationCreate
from app.schemas.ticket import TicketCreate
from app.services.customer_service import customer_service
from app.services.conversation_service import conversation_service
from app.services.ticket_service import ticket_service
from app.core.logging import get_logger

logger = get_logger(__name__)


class InboundMessageService:

    async def process(self, db: AsyncSession, event: UnifiedEvent) -> dict:
        """
        Process a unified inbound event end-to-end.
        Returns a summary dict with IDs for the created/updated entities.
        """
        tenant_id = uuid.UUID(event.tenant_id)

        # 1. Resolve or create Customer
        customer, customer_created = await customer_service.get_or_create(
            db=db,
            tenant_id=tenant_id,
            external_id=event.external_user_identifier,
            channel=event.channel,
            metadata_=event.metadata,
        )
        logger.info("customer_resolved", customer_id=str(customer.id), created=customer_created)

        # 2. Resolve open Conversation or create new one
        conversation = await conversation_service.get_open_for_customer(
            db=db,
            customer_id=customer.id,
            tenant_id=tenant_id,
            channel=event.channel,
        )
        conversation_created = False
        if not conversation:
            conv_data = ConversationCreate(
                customer_id=customer.id,
                channel=event.channel,
                subject=event.message_text[:200] if event.message_text else None,
            )
            conversation = await conversation_service.create(db, tenant_id, conv_data)
            conversation_created = True
        # Update last message preview
        if event.message_text:
            conversation.last_message_preview = event.message_text[:500]

        logger.info("conversation_resolved", conversation_id=str(conversation.id), created=conversation_created)

        # 3. Resolve or create Ticket
        ticket = await ticket_service.get_by_conversation(db, conversation.id, tenant_id)
        ticket_created = False
        if not ticket:
            ticket_data = TicketCreate(
                conversation_id=conversation.id,
                title=event.message_text[:200] if event.message_text else "New inbound message",
                priority=TicketPriority.medium,
            )
            ticket = await ticket_service.create(db, tenant_id, ticket_data)
            ticket_created = True

        logger.info("ticket_resolved", ticket_id=str(ticket.id), created=ticket_created)

        # 4. Persist EventLog
        event_log = EventLog(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            channel=event.channel,
            external_user_identifier=event.external_user_identifier,
            message_text=event.message_text,
            event_timestamp=event.timestamp,
            raw_payload=event.raw_payload,
            event_metadata=event.metadata,
            direction="inbound",
        )
        db.add(event_log)
        await db.commit()

        return {
            "event_log_id": str(event_log.id),
            "customer_id": str(customer.id),
            "conversation_id": str(conversation.id),
            "ticket_id": str(ticket.id),
            "customer_created": customer_created,
            "conversation_created": conversation_created,
            "ticket_created": ticket_created,
        }


inbound_service = InboundMessageService()
