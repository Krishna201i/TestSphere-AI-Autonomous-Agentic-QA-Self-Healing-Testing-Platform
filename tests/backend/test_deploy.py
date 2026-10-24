"""
Verified deploy (loop stage 6): deploy hook -> health -> smoke tests ->
rollback on failure.  Hooks and the site are an httpx mock; nothing leaves
the machine.
"""

import asyncio
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.models import DEPLOYMENTS, PROJECTS
from backend.pipeline import deploy
from backend.pipeline.deploy_config import DeployConfigError, check_hook_url, with_ref
from backend.services.application_service import ApplicationService
from backend.services.project_service import ProjectService
from backend.services.test_case_service import TestCaseService

RENDER = "https://api.render.com/deploy/srv-abc?key=secret"
SITE = "https://shop.example/"
GOOD = "a" * 40


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_TARGETS", True)  # no DNS for the fake site
    monkeypatch.setattr(settings, "DEPLOY_POLL_SECONDS", 0)
    monkeypatch.setattr(settings, "DEPLOY_HEALTHY_CHECKS", 2)
    monkeypatch.setattr(settings, "DEPLOY_SETTLE_SECONDS", 0)
    monkeypatch.setattr(settings, "DEPLOY_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr(deploy, "remote_head", lambda repo: "b" * 40 if repo else None)


class Site:
    """Fake hosting: hooks switch which version the site serves."""

    def __init__(self, after_deploy="v2 ok", after_rollback="v1 ok", hook_status=200):
        self.body, self.status = "v1 ok", 200
        self.after_deploy, self.after_rollback, self.hook_status = after_deploy, after_rollback, hook_status
        self.hooks: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.hooks.append(str(request.url))
            rollback = "ref" in parse_qs(urlsplit(str(request.url)).query) or "rollback" in str(request.url)
            target = self.after_rollback if rollback else self.after_deploy
            if target is None:
                self.status = 503
            else:
                self.body, self.status = target, 200
            return httpx.Response(self.hook_status, json={"ok": True})
        return httpx.Response(self.status, text=self.body)


class Smoke:
    def __init__(self, status="PASSED"):
        self.status, self.ran = status, 0

    async def execute_test_run(self, db, execution_id, options=None):
        self.ran += 1
        return {"status": self.status, "error_message": None if self.status == "PASSED" else "Timeout on #login"}


def project(db, **fields):
    p = ProjectService.create_project(db, name="Shop", owner_uid="local-dev", app_url=SITE,
                                      repo_url="https://github.com/acme/shop", deploy_hook_url=RENDER, **fields)
    application = ApplicationService.create_application(db, p["id"], name="Shop", base_url=SITE)
    TestCaseService.create_test_case(db, application["id"], external_id="pipe-smoke", name="Smoke: Shop", category="smoke")
    return p


def run(db, proj, site, smoke=None):
    dep = deploy.create_deployment(db, proj, actor="tester")
    return asyncio.run(deploy.execute_deployment(dep["id"], transport=httpx.MockTransport(site),
                                                 orchestrator=smoke or Smoke()))


def step(dep, key):
    return next(s for s in dep["steps"] if s["key"] == key)


def test_a_healthy_deploy_with_passing_smoke_tests_is_verified(fresh_store):
    site, smoke = Site(), Smoke()
    dep = run(fresh_store, project(fresh_store), site, smoke)
    assert dep["status"] == "verified", dep
    assert dep["commit"] == "b" * 40
    assert site.hooks == [RENDER]
    assert step(dep, "deploy")["status"] == "done" and "commit bbbbbbb" in step(dep, "deploy")["detail"]
    assert step(dep, "health")["status"] == "done" and "page changed" in step(dep, "health")["detail"]
    assert step(dep, "smoke")["status"] == "done" and smoke.ran == 1
    assert step(dep, "rollback")["status"] == "skipped"
    proj = fresh_store.find(PROJECTS)[0]
    assert proj["last_deploy_status"] == "verified"


def test_failing_smoke_tests_redeploy_the_last_verified_commit_on_render(fresh_store):
    proj = project(fresh_store)
    fresh_store.insert(DEPLOYMENTS, project_id=proj["id"], owner_uid="local-dev", status="verified", commit=GOOD)
    site = Site()
    dep = run(fresh_store, proj, site, Smoke("FAILED"))
    assert dep["status"] == "rolled_back", dep
    assert dep["rollback_to"] == GOOD
    assert parse_qs(urlsplit(site.hooks[1]).query)["ref"] == [GOOD]
    assert step(dep, "smoke")["status"] == "failed" and "Timeout on #login" in step(dep, "smoke")["detail"]
    assert step(dep, "rollback")["status"] == "done" and "aaaaaaa" in step(dep, "rollback")["detail"]
    assert "Smoke tests failed" in dep["error"]


def test_a_site_that_never_gets_healthy_is_rolled_back_with_the_rollback_hook(fresh_store):
    proj = project(fresh_store, rollback_hook_url="https://api.render.com/deploy/srv-stable?key=k&rollback=1")
    site = Site(after_deploy=None)  # the new version answers 503
    dep = run(fresh_store, proj, site)
    assert dep["status"] == "rolled_back", dep
    assert step(dep, "health")["status"] == "failed" and "Not healthy within" in step(dep, "health")["detail"]
    assert step(dep, "smoke")["status"] == "skipped"
    assert site.hooks[1].endswith("rollback=1")


def test_without_a_rollback_path_the_deploy_is_marked_failed(fresh_store):
    proj = project(fresh_store)
    fresh_store.update(PROJECTS, proj["id"], deploy_hook_url="https://api.vercel.com/v1/integrations/deploy/prj/x")
    dep = run(fresh_store, fresh_store.get(PROJECTS, proj["id"]), Site(), Smoke("FAILED"))
    assert dep["status"] == "failed"
    assert "No rollback configured" in step(dep, "rollback")["detail"]


def test_a_rollback_that_does_not_recover_is_reported(fresh_store):
    proj = project(fresh_store, rollback_hook_url="https://api.render.com/deploy/srv-stable?key=k&rollback=1")
    dep = run(fresh_store, proj, Site(after_deploy=None, after_rollback=None))
    assert dep["status"] == "rollback_failed"


def test_a_rejected_deploy_hook_stops_before_anything_else(fresh_store):
    site = Site(hook_status=401)
    dep = run(fresh_store, project(fresh_store), site)
    assert dep["status"] == "failed" and "HTTP 401" in dep["error"]
    assert [step(dep, k)["status"] for k in ("health", "smoke", "rollback")] == ["skipped"] * 3


@pytest.mark.parametrize("url", [
    "http://api.render.com/deploy/x",          # not https
    "https://evil.example/deploy",              # not allow-listed
    "https://user:pw@api.render.com/deploy/x",  # credentials
    "https://api.render.com:8443/deploy/x",
])
def test_hooks_only_go_to_allow_listed_https_hosts(url):
    with pytest.raises(DeployConfigError):
        check_hook_url(url)


def test_extra_hook_hosts_and_ref(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOY_HOOK_HOSTS", "deploy.internal.example")
    assert check_hook_url("https://deploy.internal.example/hook") == "https://deploy.internal.example/hook"
    assert check_hook_url(" ") == ""
    assert with_ref(RENDER + "&ref=old", GOOD) == f"https://api.render.com/deploy/srv-abc?key=secret&ref={GOOD}"


def test_deploy_api(monkeypatch):
    started = []

    async def fake(dep_id):
        started.append(dep_id)

    monkeypatch.setattr(deploy, "execute_deployment", fake)
    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "Shop", "app_url": SITE}).json()
    assert client.post(f"/api/pipelines/projects/{proj['id']}/deploy").status_code == 422  # no hook yet
    bad = client.put(f"/api/projects/{proj['id']}", json={"deploy_hook_url": "https://evil.example/x"})
    assert bad.status_code == 422
    client.put(f"/api/projects/{proj['id']}", json={"deploy_hook_url": RENDER, "deploy_on_pass": True})

    created = client.post(f"/api/pipelines/projects/{proj['id']}/deploy")
    assert created.status_code == 201 and created.json()["status"] == "queued"
    assert client.post(f"/api/pipelines/projects/{proj['id']}/deploy").status_code == 409  # one at a time
    listed = client.get("/api/pipelines/deployments", params={"project_id": proj["id"]}).json()
    assert [d["id"] for d in listed] == [created.json()["id"]]
    assert client.get(f"/api/pipelines/deployments/{created.json()['id']}").json()["provider"] == "render"


def test_restart_marks_unfinished_deployments(fresh_store):
    fresh_store.insert(DEPLOYMENTS, project_id=1, status="verifying", owner_uid="x")
    assert deploy.recover_interrupted(fresh_store) == 1
    assert fresh_store.find(DEPLOYMENTS)[0]["status"] == "error"


def test_a_clean_pipeline_run_deploys_when_the_project_asks(fresh_store, monkeypatch):
    from backend.pipeline import runner

    started = []
    monkeypatch.setattr(deploy, "start_deployment", lambda db, p, **kw: started.append(kw))
    proj = project(fresh_store, deploy_on_pass=True)
    runner._deploy_if_green(fresh_store, proj, {"id": 4, "status": "passed", "regressions": [], "actor": "me"})
    runner._deploy_if_green(fresh_store, proj, {"id": 5, "status": "failed", "regressions": []})
    runner._deploy_if_green(fresh_store, proj, {"id": 6, "status": "passed", "regressions": [{"kind": "test"}]})
    assert started == [{"actor": "me", "trigger": "pipeline", "run_id": 4}]
