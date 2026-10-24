"""
TestSphere-AI — API Package.
"""

from backend.api.applications import router as applications_router
from backend.api.audit import router as audit_router
from backend.api.health import router as health_router
from backend.api.ingest import router as ingest_router
from backend.api.me import router as me_router
from backend.api.patches import router as patches_router
from backend.api.pipelines import router as pipelines_router
from backend.api.projects import router as projects_router
from backend.api.security import router as security_router
from backend.api.system import router as system_router
from backend.api.test_cases import router as test_cases_router
from backend.api.test_executions import router as test_executions_router
from backend.api.webhooks import router as webhooks_router
from backend.api.workflow import router as workflow_router

__all__ = [
    "me_router",
    "patches_router",
    "pipelines_router",
    "webhooks_router",
    "ingest_router",
    "system_router",
    "audit_router",
    "health_router",
    "projects_router",
    "security_router",
    "applications_router",
    "test_cases_router",
    "test_executions_router",
    "workflow_router",
]

