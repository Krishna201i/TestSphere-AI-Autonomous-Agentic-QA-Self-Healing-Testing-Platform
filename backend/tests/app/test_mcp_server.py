"""MCP server: JSON-RPC over stdio, tools that drive the TestSphere API (mocked here)."""

import io
import json

import httpx

from backend import mcp_server

RUN_DONE = {"id": 7, "status": "failed", "app_url": "https://shop.test/", "error": None,
            "summary": {"total": 3, "passed": 2, "failed": 1, "healed": 1, "goal_untested_parts": ["fly to the moon"],
                        "findings": {"medium": 2}},
            "stages": [{"key": "plan", "label": "Test planning", "status": "done", "detail": "3 tests"}],
            "tests": [{"name": "Scenario: log in", "status": "FAILED",
                       "error": "Check: the sign-in form (it should be gone)\nmore"}]}


def api(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/pipelines/quick":
        body = json.loads(request.content)
        assert body == {"url": "https://shop.test/", "prompt": "log in", "repo_url": None}
        return httpx.Response(202, json={**RUN_DONE, "status": "queued"})
    if path == "/api/pipelines/runs/7":
        return httpx.Response(200, json=RUN_DONE)
    if path == "/api/security/findings":
        return httpx.Response(200, json=[
            {"status": "open", "severity": "low", "title": "No CSP", "check_id": "SEC-HDR-CSP", "component": "https://shop.test/",
             "recommendation": "Add a Content-Security-Policy"},
            {"status": "resolved", "severity": "high", "title": "old", "check_id": "X", "component": "y"},
            {"status": "open", "severity": "high", "title": "axios 1.6.2: CVE-1", "check_id": "SEC-DEP-G", "component": "npm:axios"}])
    if path == "/api/ingest":
        return httpx.Response(201, json={"dependency_scan": {"checked": 10, "vulnerable": 1, "error": None, "advisories": [
            {"severity": "high", "package": "axios", "version": "1.6.2", "cves": ["CVE-1"], "id": "G", "fixed_in": "1.8.2",
             "summary": "Prototype pollution"}]}})
    return httpx.Response(404, json={"detail": "Not Found"})


def session(*messages):
    stdin = io.StringIO("".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in messages))
    stdout = io.StringIO()
    client = httpx.Client(base_url="http://ts.test", transport=httpx.MockTransport(api))
    mcp_server.serve(stdin, stdout, client)
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def test_handshake_and_tool_list():
    replies = session({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                      {"jsonrpc": "2.0", "method": "notifications/initialized"},
                      {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                      {"jsonrpc": "2.0", "id": 3, "method": "nope"}, "not json")
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18" and replies[0]["result"]["capabilities"] == {"tools": {}}
    names = [t["name"] for t in replies[1]["result"]["tools"]]
    assert names == ["test_site", "get_run", "list_findings", "scan_dependencies", "get_fix_patch"]
    assert all(t["inputSchema"]["type"] == "object" for t in replies[1]["result"]["tools"])
    assert replies[2]["error"]["code"] == -32601
    assert replies[3]["error"]["code"] == -32700  # the notification got no reply; bad JSON did


def call(name, arguments):
    (reply,) = session({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    return reply["result"]["isError"], reply["result"]["content"][0]["text"]


def test_test_site_waits_and_reports_what_failed_and_what_was_not_tested(monkeypatch):
    monkeypatch.setattr(mcp_server, "_wait", lambda seconds: None)
    error, text = call("test_site", {"url": "https://shop.test/", "goal": "log in"})
    assert not error
    assert "Run #7 on https://shop.test/: FAILED" in text and "2/3 passed" in text
    assert "Not tested from your goal: fly to the moon" in text
    assert "FAILED Scenario: log in: Check: the sign-in form" in text and "more" not in text


def test_findings_dependencies_and_errors():
    error, text = call("list_findings", {})
    assert not error and text.splitlines()[0] == "2 open finding(s):"
    assert text.index("axios") < text.index("No CSP")  # most severe first
    error, text = call("scan_dependencies", {"repo": "https://github.com/a/b"})
    assert "1 of 10 pinned packages" in text and "fixed in 1.8.2" in text
    error, text = call("get_run", {"run_id": 404})
    assert error and "TestSphere answered 404" in text
    error, text = call("get_run", {})
    assert error and text.startswith("Bad arguments")
