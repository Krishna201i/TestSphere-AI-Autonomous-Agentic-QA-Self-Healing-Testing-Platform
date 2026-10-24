"""
End-to-end: the real backend serving the real built dashboard, in Chromium.

Every page must render its main content with no uncaught JavaScript error,
and the privacy notice must be reachable before sign-in.  Needs the built
dashboard (``cd frontend && npm run build``); skipped without it.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "frontend" / "dist" / "index.html"
AXE = ROOT / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
WCAG_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]

pytestmark = pytest.mark.skipif(not DIST.exists(), reason="dashboard not built (cd frontend && npm run build)")

PAGES = [
    ("", "#workflow-title"),
    ("autopilot", "h1:has-text('Autopilot')"),
    ("reports", "h1:has-text('Reports')"),
    ("security/attacker", "h1:has-text('AI Attacker Agent')"),
    ("security/remediation", "h1:has-text('Self-Healing Remediation Bridge')"),
    ("security/validation", "h1:has-text('Validation Engine')"),
    ("visualizer", "main"),
    ("audit", "h1:has-text('Audit')"),
    ("profile", "h1:has-text('Profile')"),
    ("privacy", "h1:has-text('Privacy')"),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port = _free_port()
    env = {**os.environ, "DATABASE_BACKEND": "local", "AUTH_REQUIRED": "false", "SCHEDULER_ENABLED": "false",
           "LOCAL_DB_PATH": str(tmp_path_factory.mktemp("db") / "db.json"), "LOG_FORMAT": "text"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("backend did not start")
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.mark.parametrize(("route", "selector"), PAGES, ids=[p[0] or "home" for p in PAGES])
def test_every_page_renders_without_errors(server, browser, route, selector):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/#/{route}")
    page.wait_for_selector(selector, timeout=15_000)
    page.wait_for_timeout(500)  # let the first data refresh settle
    assert "Backend unreachable" not in page.content()
    assert errors == []
    page.close()


@pytest.mark.skipif(not AXE.exists(), reason="axe-core not installed (cd frontend && npm ci)")
@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize(("route", "selector"), PAGES, ids=[p[0] or "home" for p in PAGES])
def test_every_page_meets_wcag_21_aa(server, browser, route, selector, scheme):
    """axe-core automated checks (contrast, names, labels, ARIA) in both themes; not a substitute for a manual audit."""
    # Reduced motion: axe must measure final colours, not a fade-in halfway through
    page = browser.new_page(viewport={"width": 1280, "height": 900}, color_scheme=scheme, reduced_motion="reduce")
    page.goto(f"{server}/#/{route}")
    page.wait_for_selector(selector, timeout=15_000)
    page.wait_for_timeout(500)
    page.add_script_tag(path=str(AXE))
    violations = page.evaluate("tags => axe.run(document, {runOnly: {type: 'tag', values: tags}}).then(r => r.violations)", WCAG_AA)
    page.close()
    assert [f"{v['id']} ({len(v['nodes'])}): {v['help']}" for v in violations] == []


def test_privacy_notice_is_reachable_before_sign_in(server, browser):
    page = browser.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def sign_in_required(route):  # pretend this server uses Firebase sign-in
        route.fulfill(json={
            "service": "TestSphere", "api_version": 3,
            "privacy": {"contact": "dpo@example.org", "ai_processing": "cloud", "error_reporting": False},
            "auth": {"required": True, "provider": "firebase",
                     "firebase": {"apiKey": "AIzaTEST", "authDomain": "demo.firebaseapp.com", "projectId": "demo"}},
        })

    page.route("**/api/system", sign_in_required)
    page.goto(server)
    page.get_by_role("button", name="How we handle your data").click()
    page.wait_for_selector("h1:has-text('Privacy')")
    assert page.get_by_role("link", name="dpo@example.org").count() == 1
    page.get_by_role("button", name="Back to sign in").click()
    page.get_by_role("button", name="Continue with Google").wait_for()
    assert errors == []
    page.close()


@pytest.mark.parametrize(("route", "selector"), PAGES, ids=[p[0] or "home" for p in PAGES])
def test_every_page_fits_a_phone(server, browser, route, selector):
    """At 390px wide nothing may push the page sideways."""
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.goto(f"{server}/#/{route}")
    page.wait_for_selector(selector, timeout=15_000)
    page.wait_for_timeout(500)
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    page.close()
    assert overflow <= 0


STAGE_KEYS = ["codebase", "analyze", "plan", "execute", "heal", "security", "report"]


def test_loop_follows_a_running_pipeline(server, browser):
    """The loop marks the running stage, the done ones before it, and shows the run in its hub."""
    statuses = ["done", "done", "done", "running", "pending", "pending", "pending"]
    run = {"id": 7, "project_id": 1, "project_name": "Shop", "status": "running", "trigger": "manual",
           "created_at": "2026-10-24T10:00:00Z", "started_at": "2026-10-24T10:00:00Z", "finished_at": None,
           "stages": [{"key": k, "label": k.title(), "status": st, "detail": None} for k, st in zip(STAGE_KEYS, statuses, strict=True)],
           "summary": None, "tests": [], "regressions": []}
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.route("**/api/pipelines/runs?*", lambda r: r.fulfill(json=[run]))
    page.goto(server)
    page.wait_for_selector(".loop-node.running")
    assert page.locator(".loop .loop-node.running").count() == 1
    assert "AI QA Agent" in page.locator(".loop .loop-node.running").inner_text()
    assert page.locator(".loop .loop-node.done").count() >= 1
    assert "run #7" in page.locator(".loop .loop-hub").inner_text().lower()
    assert page.locator(".loop .loop-token").count() == 1
    page.close()


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201e2d6a3"
    "c00000000049454e44ae426082")


def test_run_page_shows_steps_healing_and_screenshots(server, browser):
    run = {"id": 9, "project_id": 1, "project_name": "Shop", "status": "passed", "trigger": "schedule",
           "created_at": "2026-10-24T10:00:00Z", "started_at": "2026-10-24T10:00:00Z", "finished_at": "2026-10-24T10:02:00Z",
           "stages": [{"key": k, "label": k.title(), "status": "done", "detail": None} for k in STAGE_KEYS],
           "summary": {"total": 1, "passed": 1, "failed": 0, "healed": 1, "flaky": 1, "findings": None},
           "tests": [{"test_case_id": 3, "name": "Scenario: log in", "execution_id": 41, "status": "HEALED",
                      "healed": True, "flaky": True, "error": None}],
           "regressions": []}
    execution = {"id": 41, "test_case_id": 3, "status": "HEALED", "duration_ms": 900, "created_at": "2026-10-24T10:00:00Z",
                 "trace": "local-dev/executions/41/trace.zip",
                 "steps": [{"step_id": "open", "description": "Open https://shop.example/", "status": "passed", "duration_ms": 300},
                           {"step_id": "login", "description": 'Click "Log in" button', "status": "healed", "duration_ms": 600,
                            "locator": "#login-btn", "screenshot": "local-dev/executions/41/login/screenshot.png",
                            "healing": {"original_locator": "[data-testid=login]", "selected_locator": "#login-btn",
                                        "strategy": "fingerprint", "confidence": 0.87,
                                        "candidates": [{"locator": "#login-btn", "score": 0.87}, {"locator": "button", "score": 0.4}]}}]}
    page = browser.new_page(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/api/pipelines/runs/9", lambda r: r.fulfill(json=run))
    page.route("**/api/test-executions/41", lambda r: r.fulfill(json=execution))
    page.route("**/api/test-executions/41/artifact?*", lambda r: r.fulfill(body=PNG_1PX, content_type="image/png"))
    page.goto(f"{server}/#/runs/9/41")
    page.wait_for_selector(".step-list")

    assert page.locator(".step").count() == 2
    heal = page.locator(".heal-box")
    assert "[data-testid=login]" in heal.inner_text() and "#login-btn" in heal.inner_text() and "87%" in heal.inner_text()
    page.wait_for_selector(".shot img")
    assert page.locator(".shot img").evaluate("img => img.complete && img.naturalWidth > 0")
    assert page.locator(".status.FLAKY").count() >= 1
    assert page.get_by_role("button", name="Trace").count() == 1

    page.add_script_tag(path=str(AXE))
    violations = page.evaluate("tags => axe.run(document, {runOnly: {type: 'tag', values: tags}}).then(r => r.violations)", WCAG_AA)
    assert [f"{v['id']} {[n['target'] for n in v['nodes']]}: {v['help']}" for v in violations] == []

    page.locator(".shot").click()
    assert page.locator("dialog.lightbox[open]").count() == 1
    page.keyboard.press("Escape")
    assert errors == []
    page.close()


def test_fix_patch_is_shown_as_a_reviewable_diff(server, browser):
    target = "http://127.0.0.1:9/"
    finding = {"key": "k1", "check_id": "SEC-HDR-FRAME", "severity": "medium", "title": "Page can be framed",
               "status": "open", "target_url": target, "component": target, "evidence": [], "root_cause": "x",
               "recommendation": "Send X-Frame-Options", "confidence": 0.9, "first_seen": "2026-10-24T10:00:00Z",
               "last_seen": "2026-10-24T10:00:00Z",
               "remediation": {"kind": "header", "summary": "s", "diff": [{"kind": "added", "text": "X-Frame-Options: DENY"}], "snippets": {}}}
    patch = {"id": 3, "target_url": target, "repo": "https://github.com/acme/shop", "commit": "abc1234",
             "frameworks": ["fastapi"], "created_at": "2026-10-24T10:00:00Z",
             "applied": [{"check_id": "SEC-HDR-FRAME", "file": "app/main.py", "how": "HTTP middleware sets X-Frame-Options"}],
             "manual": [{"check_id": "SEC-TRANSPORT-HTTP", "reason": "Serve the site over HTTPS."}],
             "files": [{"path": "app/main.py", "verified": True, "check_note": None,
                        "diff": "--- a/app/main.py\n+++ b/app/main.py\n@@ -1,2 +1,3 @@\n app = FastAPI()\n+# fix\n x = 1\n"}],
             "patch": "..."}
    page = browser.new_page(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/api/security/findings", lambda r: r.fulfill(json=[finding]))
    page.route("**/api/security/patches?*", lambda r: r.fulfill(json=[patch]))
    page.goto(f"{server}/#/security/remediation")
    page.wait_for_selector(".udiff")
    assert page.locator(".ud-add").inner_text().strip() == "+# fix"
    assert "Serve the site over HTTPS." in page.locator("#patch-title").locator("xpath=ancestor::section").inner_text()
    assert page.get_by_role("button", name="Download .patch").count() == 1

    page.add_script_tag(path=str(AXE))
    violations = page.evaluate("tags => axe.run(document, {runOnly: {type: 'tag', values: tags}}).then(r => r.violations)", WCAG_AA)
    assert [f"{v['id']} {[n['target'] for n in v['nodes']]}" for v in violations] == []
    assert errors == []
    page.close()
