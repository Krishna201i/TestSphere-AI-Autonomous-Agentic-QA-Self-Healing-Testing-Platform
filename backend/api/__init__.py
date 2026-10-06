"""
TestSphere-AI — API Package.
"""

from backend.api.applications import router as applications_router
from backend.api.health import router as health_router
from backend.api.projects import router as projects_router
from backend.api.test_cases import router as test_cases_router
from backend.api.test_executions import router as test_executions_router
from backend.api.workflow import router as workflow_router

__all__ = [
    "health_router",
    "projects_router",
    "applications_router",
    "test_cases_router",
    "test_executions_router",
    "workflow_router",
]

