from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

# ── pgvector asyncpg codec registration ───────────────────────────────────────
# Register the pgvector codec for asyncpg connections so Python lists are
# serialised/deserialised as PostgreSQL vector values.
# This is a no-op when using SQLite (tests) or when pgvector is not installed.

_pgvector_available = False
try:
    from pgvector.asyncpg import register_vector as _register_pgvector
    _pgvector_available = True
except ImportError:
    pass


async def _asyncpg_init(conn) -> None:
    """Called by asyncpg for each new connection; registers the vector codec."""
    if _pgvector_available:
        await _register_pgvector(conn)


# Only pass the asyncpg init callback when connecting to PostgreSQL.
_connect_args: dict = {}
if settings.DATABASE_URL.startswith("postgresql"):
    _connect_args["init"] = _asyncpg_init

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    echo=settings.DEBUG,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
