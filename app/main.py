from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.api.v1.router import api_router

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
        "Phase 1: Channel adapter layer, multi-tenant foundation, RBAC. "
        "Phase 2: Async AI decision engine, job queue, structured AI results."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health endpoint
@app.get("/health", tags=["System"], summary="Health check")
async def health_check():
    """Returns service health status."""
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/", tags=["System"], include_in_schema=False)
async def root():
    return {"message": f"Welcome to {settings.APP_NAME} API", "docs": "/docs"}


# API Routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
