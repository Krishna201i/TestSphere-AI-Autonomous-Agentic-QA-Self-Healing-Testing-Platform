"""
TestSphere-AI — Main FastAPI Application Entrypoint.

Exposes REST API endpoints and coordinates the TestSphere-AI platform services.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.api import (
    applications_router,
    health_router,
    projects_router,
    test_cases_router,
    test_executions_router,
    workflow_router,
)
from backend.database.session import init_db

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
    yield
    logger.info("TestSphere-AI backend shutting down.")


app = FastAPI(
    title=settings.APP_NAME,
    description="Backend API and Application Orchestration for TestSphere-AI Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS Middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(health_router)
app.include_router(projects_router)
app.include_router(applications_router)
app.include_router(test_cases_router)
app.include_router(test_executions_router)
app.include_router(workflow_router)

# Mount frontend dashboard
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
