"""
TestSphere-AI — Main FastAPI Application Entrypoint.

Exposes REST API endpoints and coordinates the TestSphere-AI platform services.
"""

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api import (
    applications_router,
    audit_router,
    health_router,
    ingest_router,
    me_router,
    patches_router,
    pipelines_router,
    projects_router,
    security_router,
    system_router,
    test_cases_router,
    test_executions_router,
    webhooks_router,
    workflow_router,
)
from backend.config import settings, startup_safety_problem
from backend.database.session import get_store, init_db
from backend.database.store import StoreUnavailableError
from backend.netguard import check_target
from backend.observability import (
    RequestContextMiddleware,
    configure_logging,
    default_log_format,
    init_error_reporting,
)
from engine.browser import set_request_guard

configure_logging(settings.LOG_LEVEL, default_log_format())
logger = logging.getLogger("testsphere.backend")
if init_error_reporting(settings.SENTRY_DSN, settings.APP_ENV, os.getenv("RENDER_GIT_COMMIT")):
    logger.info("Error reporting to Sentry enabled")

# Browser runs fetch whatever a test step (or an LLM-planned step) points at:
# hold them to the same SSRF policy as the server's own HTTP requests.
set_request_guard(check_target)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown events."""
    if problem := startup_safety_problem():
        logger.critical("Refusing to start: %s", problem)
        raise RuntimeError(problem)
    if not settings.AUTH_REQUIRED and settings.APP_ENV != "development":
        logger.warning("Sign-in is OFF (AUTH_REQUIRED=false): anyone who can reach this server shares one account.")
    logger.info("Initializing TestSphere-AI backend services...")
    try:
        init_db()
        logger.info("Database connection verified successfully.")
    except Exception as exc:  # noqa: BLE001 - startup check: log and keep serving
        logger.warning(f"Database connection initialization check encountered: {exc}")
    try:
        from backend.pipeline.runner import recover_interrupted

        if interrupted := recover_interrupted(get_store()):
            logger.warning("Marked %d pipeline run(s) interrupted by the restart.", interrupted)
    except Exception as exc:  # noqa: BLE001 - startup check: log and keep serving
        logger.warning("Could not check for interrupted pipeline runs: %s", exc)
    scheduler_task = None
    if settings.PIPELINE_EXECUTION == "worker":
        logger.info("Pipeline runs are queued for the worker (PIPELINE_EXECUTION=worker); it also runs the scheduler.")
    elif settings.SCHEDULER_ENABLED:
        from backend.pipeline.scheduler import scheduler_loop

        scheduler_task = asyncio.create_task(scheduler_loop())
    logger.info("Sign-in %s.", "required (Firebase Auth)" if settings.AUTH_REQUIRED else "OFF: single local user")
    yield
    if scheduler_task:
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task
    logger.info("TestSphere-AI backend shutting down.")


app = FastAPI(
    title=settings.APP_NAME,
    description="Backend API and Application Orchestration for TestSphere-AI Platform",
    version="0.1.0",
    lifespan=lifespan,
)



@app.exception_handler(StoreUnavailableError)
async def database_unavailable(_request: Request, exc: StoreUnavailableError) -> JSONResponse:
    """Storage failures: 503 with a readable cause instead of a raw driver dump."""
    logger.error("Database error: %s", exc)
    return JSONResponse(status_code=503, content={"detail": f"Database unavailable: {exc}"})


# CORS: only for a dashboard hosted on another origin (CORS_ORIGINS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Outermost: request ids and the access log cover CORS answers too
app.add_middleware(RequestContextMiddleware)

# Include API routes (both under /api prefix and root for full compatibility)
api_routers = [
    health_router,
    projects_router,
    applications_router,
    test_cases_router,
    test_executions_router,
    workflow_router,
    security_router,
    audit_router,
    ingest_router,
    system_router,
    me_router,
    patches_router,
    pipelines_router,
    webhooks_router,
]
for router in api_routers:
    app.include_router(router, prefix="/api")
    app.include_router(router)

# Mount frontend dashboard (serve React production build if dist exists, else static dir)
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
frontend_dist = frontend_dir / "dist"
target_dir = frontend_dist if frontend_dist.exists() else frontend_dir
if target_dir.exists():
    app.mount("/", StaticFiles(directory=str(target_dir), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
