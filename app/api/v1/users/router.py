import uuid
from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DB, CurrentTenant, CurrentUser, OwnerOnly, AgentOrOwner
from app.schemas.user import UserCreate, UserUpdate, UserResponse
from app.schemas.common import PaginatedResponse
from app.services.user_service import user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=PaginatedResponse[UserResponse])
async def list_users(
    db: DB,
    current_tenant: CurrentTenant,
    _: AgentOrOwner,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List users in the current tenant."""
    users, total = await user_service.get_all(
        db, tenant_id=current_tenant.id, skip=(page - 1) * page_size, limit=page_size
    )
    return PaginatedResponse.create(
        items=[UserResponse.model_validate(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(body: UserCreate, db: DB, current_tenant: CurrentTenant, _: OwnerOnly):
    """Create a new user in the current tenant (owner only)."""
    user = await user_service.create(db, current_tenant.id, body)
    return UserResponse.model_validate(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: uuid.UUID, db: DB, current_tenant: CurrentTenant, _: AgentOrOwner):
    """Get a user by ID (scoped to current tenant)."""
    user = await user_service.get_by_id(db, user_id, current_tenant.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, db: DB, current_tenant: CurrentTenant, _: OwnerOnly
):
    """Update a user (owner only)."""
    user = await user_service.get_by_id(db, user_id, current_tenant.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user = await user_service.update(db, user, body)
    return UserResponse.model_validate(user)
