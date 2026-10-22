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
@pytest.mark.parametrize(("route", "selector"), PAGES, ids=[p[0] or "home" for p in PAGES])
def test_every_page_meets_wcag_21_aa(server, browser, route, selector):
    """axe-core automated checks (contrast, names, labels, ARIA); not a substitute for a manual audit."""
    page = browser.new_page(viewport={"width": 1280, "height": 900})
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
