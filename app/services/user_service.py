import uuid
from typing import Optional, List, Tuple
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.core.security import hash_password, verify_password


class UserService:

    async def get_by_id(self, db: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[User]:
        result = await db.execute(
            select(User).where(and_(User.id == user_id, User.tenant_id == tenant_id))
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, db: AsyncSession, email: str, tenant_id: uuid.UUID) -> Optional[User]:
        result = await db.execute(
            select(User).where(and_(User.email == email, User.tenant_id == tenant_id))
        )
        return result.scalar_one_or_none()

    async def get_all(
        self, db: AsyncSession, tenant_id: uuid.UUID, skip: int = 0, limit: int = 20
    ) -> Tuple[List[User], int]:
        base = select(User).where(User.tenant_id == tenant_id)
        total = (await db.execute(select(func.count()).select_from(User).where(User.tenant_id == tenant_id))).scalar_one()
        result = await db.execute(base.offset(skip).limit(limit).order_by(User.created_at.desc()))
        return result.scalars().all(), total

    async def create(self, db: AsyncSession, tenant_id: uuid.UUID, data: UserCreate) -> User:
        existing = await self.get_by_email(db, data.email, tenant_id)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered in this tenant")
        user = User(
            tenant_id=tenant_id,
            email=data.email,
            full_name=data.full_name,
            role=data.role,
            hashed_password=hash_password(data.password),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    async def update(self, db: AsyncSession, user: User, data: UserUpdate) -> User:
        update_data = data.model_dump(exclude_none=True)
        if "password" in update_data:
            update_data["hashed_password"] = hash_password(update_data.pop("password"))
        for field, value in update_data.items():
            setattr(user, field, value)
        await db.commit()
        await db.refresh(user)
        return user

    async def authenticate(
        self, db: AsyncSession, email: str, password: str, tenant_id: uuid.UUID
    ) -> Optional[User]:
        user = await self.get_by_email(db, email, tenant_id)
        if not user or not verify_password(password, user.hashed_password):
            return None
        if not user.is_active:
            return None
        return user


user_service = UserService()
