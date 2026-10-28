"""
Integrations: Slack alerts after pipeline runs, and JUnit XML export.
"""

import asyncio
import json
import xml.etree.ElementTree as ET  # parses only XML this test suite built

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.database.session import get_store
from backend.main import app
from backend.models import PIPELINE_RUNS
from backend.notify import (
    check_alert_webhook,
    notify_run,
    should_notify,
    slack_message,
    webhook_kind,
)
from backend.services.project_service import ProjectService

HOOK = "https://hooks.slack.com/services/T000/B000/XXXX"

RUN = {"id": 12, "status": "failed", "project_name": "Shop", "started_at": "2026-10-24T10:00:00+00:00",
       "summary": {"total": 3, "passed": 1, "failed": 1, "healed": 1, "flaky": 1, "previous_run_id": 11},
       "tests": [
           {"name": "Smoke", "status": "PASSED", "category": "smoke", "execution_id": 1, "healed": True},
           {"name": "Login", "status": "FAILED", "category": "functional", "execution_id": 2,
            "error": "Timeout waiting for #login\nstack...", "flaky": True},
           {"name": "Legacy", "status": "FAILED", "category": "saved", "execution_id": 3, "error": "Boom", "quarantined": True},
       ],
       "regressions": [{"kind": "test", "name": "Login", "was": "PASSED", "now": "FAILED"}]}


@pytest.mark.parametrize("url", [
    "http://hooks.slack.com/services/x",          # not https
    "https://evil.example/services/x",            # another host
    "https://hooks.slack.com.evil.example/services/x",
    "https://user@hooks.slack.com/services/x",    # credentials smuggled in
    "https://hooks.slack.com:8443/services/x",
    "https://hooks.slack.com/other",
])
def test_only_slack_incoming_webhooks_are_accepted(url):
    with pytest.raises(ValueError):
        check_alert_webhook(url)


def test_slack_webhook_accepts_and_clears():
    assert check_alert_webhook(HOOK) == HOOK
    assert check_alert_webhook("  ") == ""
    assert check_alert_webhook(None) is None


def test_when_to_notify():
    project = {"slack_webhook_url": HOOK}
    assert should_notify(project, {"status": "failed"})
    assert should_notify(project, {"status": "error"})
    assert should_notify(project, {"status": "passed", "regressions": [{"kind": "security"}]})
    assert not should_notify(project, {"status": "passed", "regressions": []})
    assert should_notify({**project, "notify_on": "always"}, {"status": "passed"})
    assert not should_notify({}, {"status": "failed"})


def test_message_names_failures_and_links_the_run(monkeypatch):
    monkeypatch.setattr(settings, "DASHBOARD_URL", "https://testsphere.example/")
    msg = slack_message({"name": "Shop"}, RUN)
    text = msg["blocks"][0]["text"]["text"]
    assert msg["text"].startswith(":x: *Shop* · run #12 failed")
    assert "1/3 tests passed · 1 self-healed · 1 flaky" in text
    assert "• Login: Timeout waiting for #login" in text and "stack" not in text
    assert "• Legacy: Boom _(quarantined)_" in text
    assert "1 regression(s) since run #11" in text
    assert msg["blocks"][1]["elements"][0]["url"] == "https://testsphere.example/#/runs/12"


def test_notify_posts_once_and_survives_slack_errors():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, text="ok")

    project = {"id": 1, "name": "Shop", "slack_webhook_url": HOOK}
    assert asyncio.run(notify_run(project, RUN, transport=httpx.MockTransport(handler))) is True
    assert len(sent) == 1 and "Shop" in sent[0]["text"]

    down = httpx.MockTransport(lambda r: httpx.Response(404, text="no_service"))
    assert asyncio.run(notify_run(project, RUN, transport=down)) is False
    assert asyncio.run(notify_run(project, {**RUN, "status": "passed", "regressions": []},
                                  transport=httpx.MockTransport(handler))) is False
    assert len(sent) == 1


def test_project_api_validates_and_stores_the_slack_settings():
    client = TestClient(app)
    project = client.post("/projects", json={"name": "Shop"}).json()
    bad = client.put(f"/projects/{project['id']}", json={"slack_webhook_url": "https://evil.example/services/x"})
    assert bad.status_code == 422
    ok = client.put(f"/projects/{project['id']}", json={"slack_webhook_url": HOOK, "notify_on": "always"}).json()
    assert ok["slack_webhook_url"] == HOOK and ok["notify_on"] == "always"
    cleared = client.put(f"/projects/{project['id']}", json={"slack_webhook_url": ""}).json()
    assert cleared["slack_webhook_url"] is None
    assert client.put(f"/projects/{project['id']}", json={"notify_on": "sometimes"}).status_code == 422


def test_junit_export_marks_failures_and_quarantine():
    db = get_store()
    project = ProjectService.create_project(db, name="Shop", owner_uid="local-dev")
    fields = {k: v for k, v in RUN.items() if k != "id"}
    run = db.insert(PIPELINE_RUNS, **fields, project_id=project["id"], owner_uid="local-dev")
    resp = TestClient(app).get(f"/api/pipelines/runs/{run['id']}/junit")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert f"testsphere-run-{run['id']}.xml" in resp.headers["content-disposition"]

    suite = ET.fromstring(resp.text).find("testsuite")
    assert suite.get("tests") == "3" and suite.get("failures") == "1" and suite.get("skipped") == "1"
    cases = {c.get("name"): c for c in suite.findall("testcase")}
    assert cases["Login"].find("failure").get("message") == "Timeout waiting for #login"
    assert "stack" in cases["Login"].find("failure").text
    assert cases["Legacy"].find("skipped").get("message") == "quarantined: Boom"
    assert cases["Smoke"].find("failure") is None
    assert "self-healed" in cases["Smoke"].find("system-out").text


def test_junit_stays_valid_xml_with_terminal_colours_and_markup():
    from backend.api.pipelines import junit_xml

    run = {"id": 1, "project_name": "A&B <shop>", "tests": [
        {"name": 'x<y "q"', "status": "FAILED", "error": "Timeout \x1b[31mred\x1b[0m & <b>"}]}
    case = ET.fromstring(junit_xml(run)).find("testsuite/testcase")
    assert case.get("name") == 'x<y "q"'
    assert case.find("failure").text == "Timeout [31mred[0m & <b>"


@pytest.mark.parametrize(("url", "kind"), [
    (HOOK, "slack"),
    ("https://discord.com/api/webhooks/123/abc", "discord"),
    ("https://chat.googleapis.com/v1/spaces/AAA/messages?key=k&token=t", "google_chat"),
    ("https://prod-12.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=x", "teams"),
    ("https://discord.com.evil.example/api/webhooks/1/a", None),
    ("https://evil.logic.azure.com.example/x", None),
    ("http://discord.com/api/webhooks/1/a", None),
])
def test_each_chat_service_is_recognised_and_nothing_else(url, kind):
    assert webhook_kind(url) == kind


@pytest.mark.parametrize(("url", "check"), [
    ("https://discord.com/api/webhooks/123/abc", lambda body: "**Shop**" in body["content"]),
    ("https://chat.googleapis.com/v1/spaces/AAA/messages?key=k", lambda body: "*Shop*" in body["text"]),
    ("https://prod-1.westus.logic.azure.com/workflows/x",
     lambda body: body["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive"),
])
def test_each_chat_service_gets_its_own_message_format(url, check):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, text="ok")

    project = {"id": 1, "name": "Shop", "slack_webhook_url": url}
    assert asyncio.run(notify_run(project, RUN, transport=httpx.MockTransport(handler))) is True
    assert check(sent[0])
    assert "Login" in json.dumps(sent[0])  # the failure is in every format
