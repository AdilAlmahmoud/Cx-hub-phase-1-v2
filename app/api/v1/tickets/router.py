import uuid
from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DB, CurrentTenant, AgentOrOwner, OwnerOnly
from app.models.ticket import TicketStatus, TicketPriority
from app.schemas.ticket import TicketCreate, TicketUpdate, TicketResponse, TicketDetailResponse, TicketFilter
from app.schemas.common import PaginatedResponse
from app.services.ticket_service import ticket_service

router = APIRouter(prefix="/tickets", tags=["Tickets"])


@router.get("", response_model=PaginatedResponse[TicketResponse])
async def list_tickets(
    db: DB,
    current_tenant: CurrentTenant,
    _: AgentOrOwner,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: TicketStatus | None = Query(None),
    priority: TicketPriority | None = Query(None),
    assigned_agent_id: uuid.UUID | None = Query(None),
):
    """List tickets for the current tenant with filters."""
    filters = TicketFilter(status=status, priority=priority, assigned_agent_id=assigned_agent_id)
    tickets, total = await ticket_service.get_all(
        db,
        tenant_id=current_tenant.id,
        skip=(page - 1) * page_size,
        limit=page_size,
        filters=filters,
    )
    return PaginatedResponse.create(
        items=[TicketResponse.model_validate(t) for t in tickets],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=TicketResponse, status_code=201)
async def create_ticket(body: TicketCreate, db: DB, current_tenant: CurrentTenant, _: AgentOrOwner):
    """Manually create a ticket."""
    from app.services.conversation_service import conversation_service
    conversation = await conversation_service.get_by_id(db, body.conversation_id, current_tenant.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    ticket = await ticket_service.create(db, current_tenant.id, body)
    await db.commit()
    return TicketResponse.model_validate(ticket)


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket(ticket_id: uuid.UUID, db: DB, current_tenant: CurrentTenant, _: AgentOrOwner):
    """Get a ticket with assigned agent detail."""
    ticket = await ticket_service.get_with_agent(db, ticket_id, current_tenant.id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return TicketDetailResponse.model_validate(ticket)


@router.patch("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: uuid.UUID, body: TicketUpdate, db: DB, current_tenant: CurrentTenant, _: AgentOrOwner
):
    """Update a ticket (status, priority, assignment, notes)."""
    ticket = await ticket_service.get_by_id(db, ticket_id, current_tenant.id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket = await ticket_service.update(db, ticket, body)
    return TicketResponse.model_validate(ticket)
