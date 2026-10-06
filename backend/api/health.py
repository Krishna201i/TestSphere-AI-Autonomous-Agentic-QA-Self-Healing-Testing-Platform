"""
TestSphere-AI — Health Check Endpoint.
"""

from typing import Dict
from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check() -> Dict[str, str]:
    """Return health status and identification of the backend service."""
    return {
        "status": "ok",
        "service": "TestSphere-AI Backend",
    }
