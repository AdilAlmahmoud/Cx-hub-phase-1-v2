"""
ARQ WorkerSettings — entry point for the background AI worker process.

Run with:
    python -m app.worker.main

Or via Docker service 'worker' (see docker-compose.yml).

The worker polls Redis for jobs enqueued by the FastAPI inbound pipeline
and calls process_ai_job() for each one.
"""
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.worker.tasks import process_ai_job  # noqa: F401 — registered via functions list

configure_logging()
logger = get_logger(__name__)


async def startup(ctx: dict) -> None:
    """Initialise shared resources for the worker process."""
    from app.core.database import AsyncSessionLocal
    ctx["db_session_factory"] = AsyncSessionLocal
    logger.info("worker_startup", provider=settings.AI_PROVIDER, redis=settings.REDIS_URL)


async def shutdown(ctx: dict) -> None:
    """Clean up worker resources."""
    logger.info("worker_shutdown")


class WorkerSettings:
    """ARQ worker configuration."""
    functions = [process_ai_job]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 10
    job_timeout = settings.AI_JOB_TIMEOUT_SECONDS
    max_tries = settings.AI_MAX_RETRIES
    keep_result = 3600  # keep job results in Redis for 1 hour


if __name__ == "__main__":
    import asyncio
    from arq import run_worker

    asyncio.run(run_worker(WorkerSettings))
