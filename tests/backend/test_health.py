"""
TestSphere-AI — Member 3 Health Check Endpoint Tests.

Verifies that the FastAPI backend starts and responds properly to GET /health.
Compatible with standard unittest and pytest.
"""

import unittest
from fastapi.testclient import TestClient
from backend.main import app


class TestHealthEndpoint(unittest.TestCase):
    """Test suite for the GET /health backend endpoint."""

    def setUp(self) -> None:
        """Create a test client before each test."""
        self.client = TestClient(app)

    def test_health_check_status_code(self) -> None:
        """Verify GET /health returns HTTP 200."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_health_check_payload(self) -> None:
        """Verify response contains status 'ok' and identifies the backend."""
        response = self.client.get("/health")
        data = response.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("service"), "TestSphere-AI Backend")


if __name__ == "__main__":
    unittest.main()
