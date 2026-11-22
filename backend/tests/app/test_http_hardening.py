"""Security headers on TestSphere's own responses, and request limits (test report D5-D7)."""

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_every_response_carries_security_headers():
    for path in ("/api/health", "/api/projects"):
        r = client.get(path)
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert "strict-transport-security" not in r.headers  # plain http


def test_hsts_behind_an_https_proxy():
    r = client.get("/api/health", headers={"X-Forwarded-Proto": "https"})
    assert r.headers["strict-transport-security"].startswith("max-age=31536000")


def test_a_route_with_its_own_policy_keeps_it():
    from fastapi import FastAPI, Response
    from fastapi.testclient import TestClient as TC

    from backend.http_hardening import HardeningMiddleware

    inner = FastAPI()

    @inner.get("/x")
    def x():
        return Response("x", headers={"Content-Security-Policy": "sandbox"})

    inner.add_middleware(HardeningMiddleware)
    assert TC(inner).get("/x").headers["content-security-policy"] == "sandbox"


def test_oversized_bodies_are_refused():
    r = client.post("/api/projects", json={"name": "big", "description": "y" * (2 * 1024 * 1024)})
    assert r.status_code == 413 and "larger than 1 MB" in r.json()["detail"]
    assert client.post("/api/projects", json={"name": "ok", "description": "y" * 6000}).status_code == 422


def test_prompt_and_step_limits():
    r = client.post("/api/workflow/plan-and-execute", json={"app_url": "https://shop.example/", "prompt": "x" * 3000})
    assert r.status_code == 422
    r = client.post("/api/workflow/plan-and-execute", json={"app_url": "https://shop.example/", "steps": [{"action": "click"}] * 101})
    assert r.status_code == 422
