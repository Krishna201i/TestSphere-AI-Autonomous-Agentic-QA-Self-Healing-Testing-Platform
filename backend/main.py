"""
TestSphere-AI — Main FastAPI Application Entrypoint.

Exposes REST API endpoints and coordinates the TestSphere-AI platform services.
"""

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.api import (
    applications_router,
    audit_router,
    health_router,
    ingest_router,
    me_router,
    pipelines_router,
    projects_router,
    security_router,
    system_router,
    test_cases_router,
    test_executions_router,
    webhooks_router,
    workflow_router,
)
from backend.database.session import get_store, init_db
from backend.database.store import StoreUnavailableError

logger = logging.getLogger("testsphere.backend")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown events."""
    logger.info("Initializing TestSphere-AI backend services...")
    try:
        init_db()
        logger.info("Database connection verified successfully.")
    except Exception as exc:
        logger.warning(f"Database connection initialization check encountered: {exc}")
    try:
        from backend.pipeline.runner import recover_interrupted

        if interrupted := recover_interrupted(get_store()):
            logger.warning("Marked %d pipeline run(s) interrupted by the restart.", interrupted)
    except Exception as exc:
        logger.warning("Could not check for interrupted pipeline runs: %s", exc)
    scheduler_task = None
    if settings.SCHEDULER_ENABLED:
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


# CORS Middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
