from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List, Optional
import secrets


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "CX Agent Hub"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # API
    API_V1_PREFIX: str = "/api/v1"

    # Security
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours
    ALGORITHM: str = "HS256"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://cxhub:cxhub_pass@localhost:5432/cxhub"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # Rate limiting (future)
    RATE_LIMIT_PER_MINUTE: int = 100

    # ── Phase 2: Queue (ARQ / Redis) ───────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379"
    # Set False to skip queue enqueue (e.g. in unit tests that call worker directly)
    AI_QUEUE_ENABLED: bool = True

    # ── Phase 2: AI Provider ───────────────────────────────────────────────────
    AI_PROVIDER: str = "mock"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    AI_MAX_RETRIES: int = 3
    AI_JOB_TIMEOUT_SECONDS: int = 300

    # ── Phase 3: Knowledge Base / RAG ─────────────────────────────────────────
    # Local filesystem path where uploaded knowledge files are stored.
    # Map this to a Docker volume in production.
    KNOWLEDGE_STORAGE_PATH: str = "./data/knowledge"
    # Embedding provider: "mock" or "openai"
    EMBEDDING_PROVIDER: str = "mock"
    # OpenAI model used for embeddings (only when EMBEDDING_PROVIDER=openai)
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    # Embedding vector dimensions (must match the model; 1536 for ada-002 / 3-small)
    EMBEDDING_DIMENSIONS: int = 1536
    # Text chunk size in characters for ingestion pipeline
    KNOWLEDGE_CHUNK_SIZE: int = 1000
    # Overlap between consecutive chunks in characters
    KNOWLEDGE_CHUNK_OVERLAP: int = 100

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
