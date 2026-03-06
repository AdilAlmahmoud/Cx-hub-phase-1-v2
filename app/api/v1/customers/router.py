import uuid
from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DB, CurrentTenant, AgentOrOwner
from app.schemas.customer import CustomerCreate, CustomerUpdate, CustomerResponse
from app.schemas.common import PaginatedResponse
from app.services.customer_service import customer_service

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=PaginatedResponse[CustomerResponse])
async def list_customers(
    db: DB,
    current_tenant: CurrentTenant,
    _: AgentOrOwner,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    channel: str | None = Query(None),
):
    """List customers for the current tenant with optional channel filter."""
    customers, total = await customer_service.get_all(
        db,
        tenant_id=current_tenant.id,
        skip=(page - 1) * page_size,
        limit=page_size,
        channel=channel,
    )
    return PaginatedResponse.create(
        items=[CustomerResponse.model_validate(c) for c in customers],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(body: CustomerCreate, db: DB, current_tenant: CurrentTenant, _: AgentOrOwner):
    """Manually create a customer record."""
    customer = await customer_service.create(db, current_tenant.id, body)
    return CustomerResponse.model_validate(customer)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: uuid.UUID, db: DB, current_tenant: CurrentTenant, _: AgentOrOwner):
    """Get a customer by ID (scoped to current tenant)."""
    customer = await customer_service.get_by_id(db, customer_id, current_tenant.id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return CustomerResponse.model_validate(customer)


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: uuid.UUID, body: CustomerUpdate, db: DB, current_tenant: CurrentTenant, _: AgentOrOwner
):
    """Update a customer's details."""
    customer = await customer_service.get_by_id(db, customer_id, current_tenant.id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    customer = await customer_service.update(db, customer, body)
    return CustomerResponse.model_validate(customer)
