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
    page = browser.new_page(bypass_csp=True, viewport={"width": 1280, "height": 900})
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
    page = browser.new_page(bypass_csp=True, viewport={"width": 1280, "height": 900}, color_scheme=scheme, reduced_motion="reduce")
    page.goto(f"{server}/#/{route}")
    page.wait_for_selector(selector, timeout=15_000)
    page.wait_for_timeout(500)
    page.add_script_tag(path=str(AXE))
    violations = page.evaluate("tags => axe.run(document, {runOnly: {type: 'tag', values: tags}}).then(r => r.violations)", WCAG_AA)
    page.close()
    assert [f"{v['id']} ({len(v['nodes'])}): {v['help']}" for v in violations] == []


SHOTS = Path(os.environ["E2E_SHOTS"]) if os.getenv("E2E_SHOTS") else None


def test_privacy_notice_is_reachable_before_sign_in(server, browser):
    page = browser.new_page(bypass_csp=True)
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
    assert page.get_by_role("button", name="Continue with GitHub").count() == 1
    assert page.get_by_role("button", name="Try it as a guest").count() == 1
    if SHOTS:
        page.screenshot(path=str(SHOTS / "sign-in.png"))
    page.get_by_role("button", name="Continue with phone").click()
    page.get_by_label("Phone number").wait_for()
    assert page.get_by_role("button", name="Send code").count() == 1
    page.get_by_role("button", name="Back to sign in").click()
    page.get_by_role("button", name="Continue with Google").wait_for()
    assert errors == []
    page.close()


@pytest.mark.parametrize(("route", "selector"), PAGES, ids=[p[0] or "home" for p in PAGES])
def test_every_page_fits_a_phone(server, browser, route, selector):
    """At 390px wide nothing may push the page sideways."""
    page = browser.new_page(bypass_csp=True, viewport={"width": 390, "height": 844})
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
    page = browser.new_page(bypass_csp=True, viewport={"width": 1280, "height": 900})
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
    page = browser.new_page(bypass_csp=True, viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
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
    page = browser.new_page(bypass_csp=True, viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
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


def test_deployments_show_steps_and_drive_loop_stage_6(server, browser):
    steps = [{"key": "deploy", "label": "Deploy", "status": "done", "detail": "api.render.com accepted it (HTTP 200) · commit bbbbbbb"},
             {"key": "health", "label": "Health check", "status": "done", "detail": "Healthy 3 times in a row after the page changed (80 ms)"},
             {"key": "smoke", "label": "Smoke tests", "status": "failed", "detail": "0 of 1 passed: Smoke: Shop (Timeout)"},
             {"key": "rollback", "label": "Rollback", "status": "done", "detail": "redeploy of last verified commit aaaaaaa"}]
    dep = {"id": 4, "project_id": 1, "project_name": "Shop", "status": "rolled_back", "trigger": "pipeline", "run_id": 9,
           "commit": "b" * 40, "rollback_to": "a" * 40, "error": "Smoke tests failed", "steps": steps,
           "health": [{"ok": True, "ms": 80}, {"ok": True, "ms": 90}, {"ok": False, "ms": 0}, {"ok": True, "ms": 70}],
           "created_at": "2026-10-24T10:00:00Z", "finished_at": "2026-10-24T10:05:00Z"}
    page = browser.new_page(bypass_csp=True, viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/api/pipelines/deployments?*", lambda r: r.fulfill(json=[dep]))
    page.goto(f"{server}/#/security/validation")
    page.wait_for_selector("#deploy-title")
    card = page.locator("section:has(#deploy-title)")
    assert "rolled back" in card.inner_text().lower() and "redeploy of last verified commit" in card.inner_text()
    assert card.locator(".stage-item.failed").count() == 1

    page.add_script_tag(path=str(AXE))
    violations = page.evaluate("tags => axe.run(document, {runOnly: {type: 'tag', values: tags}}).then(r => r.violations)", WCAG_AA)
    assert [f"{v['id']} {[n['target'] for n in v['nodes']]}" for v in violations] == []

    page.goto(f"{server}/#/")
    page.wait_for_selector(".loop .loop-node")
    stage6 = page.locator(".loop .loop-node").filter(has_text="Verified Deploy")
    assert "Rolled back" in stage6.inner_text()
    assert errors == []
    page.close()


def test_the_dashboard_runs_under_its_own_content_security_policy(server, browser):
    """No CSP violations while the real dashboard loads and navigates (CSP not bypassed)."""
    page = browser.new_page()
    violations: list[str] = []
    page.on("console", lambda m: violations.append(m.text) if "Content Security Policy" in m.text else None)
    page.on("pageerror", lambda e: violations.append(str(e)))
    for route in ("", "autopilot", "reports", "security/remediation", "visualizer", "privacy"):
        page.goto(f"{server}/#/{route}")
        page.wait_for_timeout(800)
    assert "content-security-policy" in page.evaluate("() => fetch('/api/health').then(r => [...r.headers.keys()].join(','))")
    assert violations == []
    page.close()


def test_fix_patch_opens_a_pull_request(server, browser):
    target = "http://127.0.0.1:9/"
    finding = {"key": "k1", "check_id": "SEC-HDR-FRAME", "severity": "medium", "title": "Page can be framed",
               "status": "open", "target_url": target, "component": target, "evidence": [], "root_cause": "x",
               "recommendation": "Send X-Frame-Options", "confidence": 0.9, "first_seen": "2026-10-24T10:00:00Z",
               "last_seen": "2026-10-24T10:00:00Z", "remediation": {"kind": "header", "summary": "s", "diff": [], "snippets": {}}}
    patch = {"id": 5, "target_url": target, "repo": "https://github.com/acme/shop", "commit": "b" * 40, "github": True,
             "pull_request": None, "frameworks": ["fastapi"], "created_at": "2026-10-24T10:00:00Z", "manual": [],
             "applied": [{"check_id": "SEC-HDR-FRAME", "file": "app/main.py", "how": "HTTP middleware sets X-Frame-Options"}],
             "files": [{"path": "app/main.py", "verified": True, "check_note": None,
                        "diff": "--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1,2 @@\n app = FastAPI()\n+# fix\n"}], "patch": "..."}
    page = browser.new_page(bypass_csp=True, viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/api/security/findings", lambda r: r.fulfill(json=[finding]))
    page.route("**/api/security/patches?*", lambda r: r.fulfill(json=[patch]))
    page.route("**/api/security/patches/5/pull-request",
               lambda r: r.fulfill(status=201, json={"url": "https://github.com/acme/shop/pull/12", "number": 12,
                                                    "branch": "testsphere/fix-5", "base": "main"}))
    page.goto(f"{server}/#/security/remediation")
    page.get_by_role("button", name="Open pull request").click()
    link = page.get_by_role("link", name="Pull request #12")
    link.wait_for()
    assert link.get_attribute("href") == "https://github.com/acme/shop/pull/12"
    assert "bbbbbbb" in page.locator("#patch-title").locator("xpath=ancestor::section").inner_text()
    assert errors == []
    page.close()


def test_a_long_failure_does_not_squeeze_the_report_table(server, browser):
    """A test's name stays readable and a long error shows its first lines, not the whole page text."""
    # Older runs stored the page text escaped: a backslash and an n for each line break
    page_text = r"Skip to main content\nCareLink\nECOSYSTEM\n" + "Portals and the mobile app share one backend. " * 80
    tests = [
        {"test_case_id": 1, "name": "Content: heading 'The Modern Operating System for National'", "category": "content",
         "execution_id": 264, "status": "FAILED",
         "error": f"assert_text failed: expected 'The Modern Operating System for National' in \"{page_text}\""},
        {"test_case_id": 2, "name": "AI: Load Home Page", "category": "ai", "execution_id": 265, "status": "PASSED", "error": None},
    ]
    run = {"id": 12, "project_id": 1, "project_name": "CareLink", "status": "failed", "trigger": "manual",
           "created_at": "2026-10-30T08:40:00Z", "started_at": "2026-10-30T08:40:00Z", "finished_at": "2026-10-30T08:45:00Z",
           "stages": [{"key": k, "label": k.title(), "status": "done", "detail": None} for k in STAGE_KEYS],
           "summary": {"total": 2, "passed": 1, "failed": 1}, "tests": tests, "regressions": []}
    page = browser.new_page(bypass_csp=True, viewport={"width": 1440, "height": 900})
    page.route("**/api/pipelines/runs?*", lambda r: r.fulfill(json=[run]))
    page.goto(f"{server}/#/autopilot")
    row = page.locator("tr", has_text="execution #264")
    row.wait_for()
    name_cell, error_cell = row.locator("td").nth(0), row.locator("td").nth(2)

    assert name_cell.bounding_box()["width"] >= 200, "the name column is squeezed"
    clamp = error_cell.locator(".cell-clamp")
    line_height, shown, full = clamp.evaluate(
        "e => [parseFloat(getComputedStyle(e).lineHeight), e.clientHeight, e.scrollHeight]")
    assert shown <= line_height * 3 + 2, "the error is not cut to 3 lines"
    assert full > shown, "the rest of a long error is hidden"
    assert "\\n" not in error_cell.inner_text()  # old, escaped messages read as plain text
    assert error_cell.locator(".cell-clamp").get_attribute("title").startswith("assert_text failed")  # full text on hover
    if os.getenv("E2E_SCREENSHOT_DIR"):
        page.locator(".table-wrap", has_text="execution #264").screenshot(path=os.path.join(os.environ["E2E_SCREENSHOT_DIR"], "report-table.png"))
    page.close()


def _report_run(run_id, finished, tests):
    passed = sum(t["status"] == "PASSED" for t in tests)
    return {"id": run_id, "project_id": 1, "project_name": "CareLink", "status": "failed" if passed < len(tests) else "passed",
            "trigger": "manual", "created_at": finished, "started_at": finished, "finished_at": finished,
            "stages": [{"key": k, "label": k.title(), "status": "done", "detail": None} for k in STAGE_KEYS],
            "summary": {"total": len(tests), "passed": passed, "failed": len(tests) - passed, "healed": 0},
            "tests": tests, "regressions": []}


def test_reports_are_organised_by_run_and_test_type_with_details_for_every_test(server, browser):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    latest = _report_run(31, now, [
        {"test_case_id": 1, "name": "Smoke: CareLink", "category": "smoke", "execution_id": 308, "status": "PASSED",
         "checks": ["Page title contains 'CareLink'", "Page shows the body"], "duration_ms": 1830},
        {"test_case_id": 2, "name": "Linked page: /hospital/", "category": "link", "execution_id": 316, "status": "PASSED",
         "duration_ms": 2400},  # an older result: no recorded checks
        {"test_case_id": 3, "name": "AI: Navigate to Hospital Portal", "category": "ai", "execution_id": 312, "status": "FAILED",
         "quarantined": True, "error": "assert_url failed: expected '/hospital/', got '/'", "duration_ms": 5200},
    ])
    older = _report_run(30, now, [
        {"test_case_id": 1, "name": "Smoke: CareLink", "category": "smoke", "execution_id": 290, "status": "PASSED"}])
    page = browser.new_page(bypass_csp=True, viewport={"width": 1280, "height": 900})
    page.route("**/api/pipelines/runs?*", lambda r: r.fulfill(json=[latest, older]))
    page.goto(f"{server}/#/reports")
    run = page.locator("section.report-run", has_text="Run #31")
    run.wait_for()

    assert page.locator("section.report-run").count() == 2
    assert "2/3 passed" in run.locator(".report-run-meta").inner_text()
    groups = [t.split("\n")[0] for t in run.locator(".report-group-title").all_inner_texts()]
    assert [g.split(" ")[0] for g in groups] == ["Smoke", "Linked", "AI-written"]  # report order, not run order
    details = {r.locator("td").nth(0).inner_text().split("\n")[0]: r.locator("td").nth(2).inner_text()
               for r in run.locator("tbody tr").all()}
    assert details["Smoke: CareLink"].startswith("Page title contains 'CareLink' · Page shows the body") and "1.8 s" in details["Smoke: CareLink"]
    assert details["Linked page: /hospital/"].startswith("Linked page loads with its title and heading")
    assert details["AI: Navigate to Hospital Portal"].startswith("assert_url failed")
    assert all(d.strip() not in ("", "—") for d in details.values()), "a test without details"

    if os.getenv("E2E_SCREENSHOT_DIR"):
        shots = os.environ["E2E_SCREENSHOT_DIR"]
        run.screenshot(path=os.path.join(shots, "report-run.png"))
        page.emulate_media(media="print")
        page.pdf(path=os.path.join(shots, "report.pdf"), format="A4", print_background=True)
    page.close()
