"""
TestSphere-AI — API Package.
"""

from app.api.applications import router as applications_router
from app.api.audit import router as audit_router
from app.api.heals import router as heals_router
from app.api.health import router as health_router
from app.api.ingest import router as ingest_router
from app.api.integrations import router as integrations_router
from app.api.me import router as me_router
from app.api.patches import router as patches_router
from app.api.pipelines import router as pipelines_router
from app.api.projects import router as projects_router
from app.api.security import router as security_router
from app.api.shares import public_router as shared_reports_router
from app.api.shares import router as shares_router
from app.api.studio import router as studio_router
from app.api.system import router as system_router
from app.api.test_cases import router as test_cases_router
from app.api.test_executions import router as test_executions_router
from app.api.webhooks import router as webhooks_router
from app.api.workflow import router as workflow_router

__all__ = [
    "me_router",
    "integrations_router",
    "patches_router",
    "pipelines_router",
    "webhooks_router",
    "shares_router",
    "shared_reports_router",
    "ingest_router",
    "studio_router",
    "system_router",
    "audit_router",
    "heals_router",
    "health_router",
    "projects_router",
    "security_router",
    "applications_router",
    "test_cases_router",
    "test_executions_router",
    "workflow_router",
]

