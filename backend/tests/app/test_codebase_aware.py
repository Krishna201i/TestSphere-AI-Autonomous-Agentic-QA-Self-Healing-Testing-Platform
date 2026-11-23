"""Codebase-aware Test Studio: Playwright tests imported as text, and flows suggested from the code and page."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import studio as studio_api
from app.database.session import get_store
from app.main import app
from app.models import BLUEPRINTS
from app.services import flow_suggest
from app.services.playwright_import import SPEC_FILE, parse_spec
from app.services.url_analyzer import URLAnalyzerService

URL = "https://shop.example/"
ANALYSIS = {"success": True, "url": URL, "page_title": "Shop",
            "elements_inventory": {"inputs": [{"selector": "#q", "type": "search", "name": "q"}],
                                   "buttons": [{"selector": "#go", "text": "Search"}], "headings": ["Products"]}}

SPEC = r'''
import { test, expect } from '@playwright/test';
test('signs in', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Email').fill('demo@example.com');
  await page.getByPlaceholder('Password').fill(process.env.PASSWORD!);
  const submit = page.getByRole('button', { name: 'Log in' });
  await submit.click();
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole('heading', { name: 'Welcome', exact: true })).toBeVisible();
  await expect(page.locator('#cart')
    .first()).toContainText("1 item");
  await helpers.logout(page);
});
test.skip('later', async ({ page }) => {});
test("old style", async ({ page }) => {
  await page.click('#a'); await page.fill('input[name="q"]', 'shoes');
  await expect(page.locator('.result')).not.toBeVisible();
  await expect(page).toHaveTitle('Shop');
});
'''


@pytest.fixture(autouse=True)
def fake_page(monkeypatch):
    async def analyze(url, prompt=None, **_):
        return {**ANALYSIS, "url": url}

    monkeypatch.setattr(URLAnalyzerService, "analyze_live_website", analyze)
    studio_api._analyses.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project(client):
    return client.post("/projects", json={"name": "Shop", "app_url": URL, "repo_url": "https://github.com/acme/shop"}).json()


# ---------------------------------------------------------------------------
# Reading Playwright tests
# ---------------------------------------------------------------------------


def test_locators_keep_playwrights_meaning():
    signs_in = parse_spec(SPEC)["tests"][0]
    targets = [s["target"] for s in signs_in["steps"]]
    assert targets == [None, 'internal:label="Email"i', 'internal:role=button[name="Log in"i]', None,
                       'internal:role=heading[name="Welcome"s]', "#cart >> nth=0"]
    assert [s["action"] for s in signs_in["steps"]] == ["NAVIGATE", "FILL", "CLICK", "ASSERT_URL", "ASSERT_VISIBLE",
                                                       "ASSERT_CONTAINS_TEXT"]
    assert signs_in["steps"][3]["value"] == "/dashboard"


def test_what_cannot_be_read_is_listed_never_guessed():
    signs_in = parse_spec(SPEC)["tests"][0]
    assert signs_in["not_imported"] == ["await page.getByPlaceholder('Password').fill(process.env.PASSWORD!)",
                                        "await helpers.logout(page)"]


def test_old_style_calls_negations_and_titles():
    old = parse_spec(SPEC)["tests"][1]
    assert [(s["action"], s["target"], s["value"]) for s in old["steps"]] == [
        ("CLICK", "#a", None), ("FILL", 'input[name="q"]', "shoes"), ("ASSERT_HIDDEN", ".result", None),
        ("ASSERT_CONTAINS_TEXT", "head > title", "Shop")]


def test_skipped_tests_are_counted_not_imported():
    parsed = parse_spec(SPEC)
    assert [t["name"] for t in parsed["tests"]] == ["signs in", "old style"] and parsed["skipped_tests"] == 1


@pytest.mark.parametrize("line", [
    "await page.goto(baseUrl + '/x')",          # a value from code
    "await page.fill('#q', `${term}`)",         # a template with a variable
    "for (const x of items) await page.click(x)",
    "await page.evaluate(() => localStorage.clear())",
])
def test_code_is_not_imported(line):
    parsed = parse_spec(f"test('t', async ({{ page }}) => {{ {line}; }});")
    assert parsed["tests"][0]["steps"] == [] and parsed["tests"][0]["not_imported"]


def test_spec_file_names():
    assert all(SPEC_FILE.search(n) for n in ("login.spec.ts", "a/b/cart.test.js", "x.e2e.ts"))
    assert not any(SPEC_FILE.search(n) for n in ("spec.ts", "login.ts", "test.json"))


# ---------------------------------------------------------------------------
# Suggested flows
# ---------------------------------------------------------------------------

BLUEPRINT = {"name": "shop", "frameworks": ["FastAPI", "React"], "test_suites": [{"framework": "Playwright"}],
             "routes": [{"method": "POST", "path": "/api/login"}, {"method": "GET", "path": "/register"},
                        {"method": "GET", "path": "/cart"}, {"method": "GET", "path": "/about"},
                        {"method": "GET", "path": "/items/{id}"}]}


def test_rules_find_the_critical_flows_from_routes_and_page():
    flows = flow_suggest.rule_flows(BLUEPRINT, ANALYSIS, {"username": "demo", "password": "secret"})
    names = [f["name"] for f in flows]
    assert names[:3] == ["Sign in", "Sign up", "Checkout"] and "Search" in names
    assert "Page /about" in names and not any("{id}" in n for n in names)
    sign_in = flows[0]
    assert "demo" in sign_in["instruction"] and "secret" not in sign_in["instruction"]  # a password is never written out
    assert sign_in["evidence"] == ["/api/login"]


def test_the_model_prompt_fences_code_and_page():
    prompt = flow_suggest.build_prompt(BLUEPRINT, ANALYSIS)
    assert "<<<UNTRUSTED code>>>" in prompt and "<<<UNTRUSTED page>>>" in prompt and "GET /register" in prompt


def test_model_flows_are_cleaned_and_ranked():
    flows = flow_suggest.clean_flows({"flows": [
        {"name": "About", "risk": "low", "instruction": "Open about"},
        {"name": "Pay", "risk": "HIGH", "why": "money", "instruction": "Pay for the cart"},
        {"name": "Bad", "risk": "weird", "instruction": "x"}, {"name": "Empty", "instruction": " "}, "junk"]})
    assert [(f["name"], f["risk"]) for f in flows] == [("Pay", "high"), ("Bad", "medium"), ("About", "low")]


class FakeLLM:
    def __init__(self, answer):
        self.answer, self.requests = answer, []

    async def generate_json(self, request):
        self.requests.append(request)
        return self.answer


def test_suggest_uses_the_latest_blueprint_and_the_model(client, project, monkeypatch):
    import json

    get_store().insert(BLUEPRINTS, source=project["repo_url"], name="shop", data=json.dumps(BLUEPRINT),
                       owner_uid=None, project_id=project["id"])
    llm = FakeLLM({"flows": [{"name": "Checkout", "risk": "high", "why": "revenue", "instruction": "Buy the first item"}]})
    monkeypatch.setattr(studio_api, "_model_enabled", lambda: True)
    monkeypatch.setattr("app.orchestration.orchestrator.create_platform_llm_client", lambda: llm)
    body = client.post(f"/projects/{project['id']}/studio/suggest", json={}).json()
    assert body["source"] == "ai" and body["flows"][0]["instruction"] == "Buy the first item"
    assert body["blueprint"]["routes"] == 5
    assert "/register" in llm.requests[0].prompt


def test_suggest_without_model_or_repository_says_so(client, project):
    body = client.post(f"/projects/{project['id']}/studio/suggest", json={}).json()
    assert body["source"] == "rules" and body["blueprint"] is None
    assert "Link a repository" in body["note"]
    assert any(f["name"] == "Search" for f in body["flows"])


# ---------------------------------------------------------------------------
# Import endpoints
# ---------------------------------------------------------------------------


def test_import_returns_checked_drafts(client, project):
    body = client.post(f"/projects/{project['id']}/studio/import", json={"text": SPEC, "filename": "e2e/auth.spec.ts"}).json()
    [f] = body["files"]
    assert f["file"] == "auth.spec.ts" and f["skipped_tests"] == 1
    signs_in, old = f["tests"]
    assert [s["status"] for s in signs_in["steps"]][:3] == ["page", "text", "text"]  # Playwright locators resolve at run time
    assert signs_in["steps"][0]["value"] == "https://shop.example/login"  # relative goto on the project's site
    assert signs_in["not_imported"] and signs_in["problems"] == []
    assert old["quarantine"] is True  # '#a' was not seen on the page


def test_import_without_tests_is_refused(client, project):
    res = client.post(f"/projects/{project['id']}/studio/import", json={"text": "export const x = 1;"})
    assert res.status_code == 422 and "No Playwright tests" in res.json()["detail"]


def test_import_from_the_repository_reads_spec_files_only(client, project, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    (repo / "e2e").mkdir(parents=True)
    (repo / "e2e" / "auth.spec.ts").write_text(SPEC, encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "math.test.ts").write_text("import { it } from 'vitest'; it('adds', () => {});", encoding="utf-8")
    (repo / "node_modules" / "x").mkdir(parents=True)
    (repo / "node_modules" / "x" / "a.spec.js").write_text(SPEC, encoding="utf-8")
    discarded = []
    monkeypatch.setattr("ingestion.source.clone", lambda url, ws, hosts, auth=None: repo)
    monkeypatch.setattr("ingestion.source.discard_checkout", lambda root: discarded.append(root))
    body = client.post(f"/projects/{project['id']}/studio/import-repo", json={}).json()
    assert [f["file"] for f in body["files"]] == ["e2e/auth.spec.ts"]
    assert discarded == [repo]  # the checkout is always removed


def test_import_from_repository_needs_one(client):
    p = client.post("/projects", json={"name": "No repo", "app_url": URL}).json()
    res = client.post(f"/projects/{p['id']}/studio/import-repo", json={})
    assert res.status_code == 422 and "no repository" in res.json()["detail"]
