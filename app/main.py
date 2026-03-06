from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestIDMiddleware
from app.api.v1.router import api_router
from app.api.deps import get_db

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", app=settings.APP_NAME, version=settings.APP_VERSION, env=settings.ENVIRONMENT)

    # Phase 2: initialise ARQ Redis pool (non-fatal if Redis is unavailable)
    from app.core.queue import init_queue, close_queue
    await init_queue()

    yield

    await close_queue()
    logger.info("shutdown", app=settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "CX Agent Hub — Multi-tenant AI-powered customer service platform. "
        "Phase 1: Channel adapters, multi-tenant foundation, RBAC. "
        "Phase 2: Async AI decision engine, job queue, structured AI results. "
        "Phase 3: Knowledge base, RAG, pgvector embeddings, real OpenAI integration. "
        "Phase 4: Outbound messaging, email channel, settings API, hardening."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Request ID middleware (Phase 4) — must be added before CORS
app.add_middleware(RequestIDMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


# ── Health endpoint (enhanced in Phase 4) ─────────────────────────────────────

@app.get("/health", tags=["System"], summary="Health check")
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Returns service health status with dependency checks.

    Checks:
    - Database connectivity (PostgreSQL)
    - Redis / queue connectivity
    """
    from app.core.queue import get_queue_pool

    # DB check
    db_ok = False
    try:
        from sqlalchemy import text
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    # Redis/queue check
    queue_pool = get_queue_pool()
    redis_ok = queue_pool is not None

    overall = "ok" if db_ok else "degraded"

    return {
        "status": overall,
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "checks": {
            "database": "ok" if db_ok else "unavailable",
            "queue": "ok" if redis_ok else "unavailable",
        },
    }


@app.get("/", tags=["System"], include_in_schema=False)
async def root():
    return {"message": f"Welcome to {settings.APP_NAME} API", "docs": "/docs"}


# API Routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
