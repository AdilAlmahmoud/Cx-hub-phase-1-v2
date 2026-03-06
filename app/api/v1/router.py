from fastapi import APIRouter
from app.api.v1.auth.router import router as auth_router
from app.api.v1.tenants.router import router as tenants_router
from app.api.v1.users.router import router as users_router
from app.api.v1.customers.router import router as customers_router
from app.api.v1.conversations.router import router as conversations_router
from app.api.v1.tickets.router import router as tickets_router
from app.api.v1.channels.router import router as channels_router
from app.api.v1.ai_jobs.router import router as ai_jobs_router
from app.api.v1.knowledge.router import router as knowledge_router
from app.api.v1.outbound.router import router as outbound_router
from app.api.v1.settings.router import router as settings_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(tenants_router)
api_router.include_router(users_router)
api_router.include_router(customers_router)
api_router.include_router(conversations_router)
api_router.include_router(tickets_router)
api_router.include_router(channels_router)
api_router.include_router(ai_jobs_router)
api_router.include_router(knowledge_router)
api_router.include_router(outbound_router)
api_router.include_router(settings_router)
