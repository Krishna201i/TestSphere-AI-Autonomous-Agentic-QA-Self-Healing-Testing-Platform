"""
TestSphere-AI — MCP server: let coding agents test, attack-check and fix the app they are building.

Runs over stdio (JSON-RPC 2.0, one message per line), the transport every MCP
client supports: Antigravity, Claude Code, Cursor, VS Code, Windsurf...  It
drives a TestSphere server through its REST API:

    TESTSPHERE_URL     the server (default http://127.0.0.1:8000)
    TESTSPHERE_TOKEN   an API token (Profile -> API tokens) when the server requires sign-in

Tools: test_site (the whole loop on a URL, waiting for the result), get_run,
list_findings, scan_dependencies and get_fix_patch.  Start it with
``python -m backend.mcp_server`` (or ``testsphere-mcp``); see
docs/mcp-server.md for each client's configuration.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from typing import Any, TextIO

import httpx

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "testsphere", "title": "TestSphere AI", "version": "0.1.0"}
RUN_TIMEOUT_S = 900
_wait: Callable[[float], None] = time.sleep  # between polls of a running pipeline


class ToolError(Exception):
    """A readable failure shown to the agent (isError: true)."""


def _api(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    headers = {"User-Agent": "testsphere-mcp"}
    if os.getenv("TESTSPHERE_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['TESTSPHERE_TOKEN']}"
    return httpx.Client(base_url=os.getenv("TESTSPHERE_URL", "http://127.0.0.1:8000").rstrip("/"),
                        headers=headers, timeout=120, transport=transport)


def _call(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    try:
        resp = client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not reach TestSphere at {client.base_url}: {exc}. Is the server running?") from exc
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = resp.text[:300]
        raise ToolError(f"TestSphere answered {resp.status_code}: {detail}")
    return resp.json() if resp.content else None


# ── Tools ──────────────────────────────────────────────────────────────────

def _describe_run(run: dict[str, Any]) -> str:
    s = run.get("summary") or {}
    lines = [f"Run #{run['id']} on {run.get('app_url', '')}: {run['status'].upper()}"]
    if s:
        lines.append(f"Tests: {s.get('passed', 0)}/{s.get('total', 0)} passed, {s.get('failed', 0)} failed, "
                     f"{s.get('healed', 0)} self-healed")
    if s.get("goal_untested"):
        lines.append("Your goal was NOT tested: no form fields or buttons were found.")
    elif s.get("goal_untested_parts"):
        lines.append("Not tested from your goal: " + "; ".join(s["goal_untested_parts"]))
    for st in run.get("stages") or []:
        lines.append(f"  [{st['status']}] {st['label']}: {st.get('detail') or ''}".rstrip(": "))
    for t in run.get("tests") or []:
        if t.get("status") == "FAILED":
            lines.append(f"  FAILED {t['name']}: {(t.get('error') or '').splitlines()[0][:300] if t.get('error') else ''}")
    findings = s.get("findings") or {}
    if findings:
        lines.append("Security findings: " + ", ".join(f"{n} {sev}" for sev, n in findings.items()))
    if run.get("error"):
        lines.append(f"Error: {run['error']}")
    return "\n".join(lines)


def test_site(client: httpx.Client, args: dict[str, Any]) -> str:
    body = {"url": args["url"], "prompt": args.get("goal") or None, "repo_url": args.get("repo_url") or None}
    run = _call(client, "POST", "/api/pipelines/quick", json=body)
    if args.get("wait", True) is False:
        return f"Started run #{run['id']}. Call get_run with run_id {run['id']} for the result."
    deadline = time.monotonic() + RUN_TIMEOUT_S
    while run["status"] in ("queued", "running") and time.monotonic() < deadline:
        _wait(3)
        run = _call(client, "GET", f"/api/pipelines/runs/{run['id']}")
    return _describe_run(run)


def get_run(client: httpx.Client, args: dict[str, Any]) -> str:
    return _describe_run(_call(client, "GET", f"/api/pipelines/runs/{int(args['run_id'])}"))


def list_findings(client: httpx.Client, args: dict[str, Any]) -> str:
    params = {"target_url": args["target_url"]} if args.get("target_url") else {}
    rows = [f for f in _call(client, "GET", "/api/security/findings", params=params) if f.get("status") == "open"]
    if not rows:
        return "No open security findings."
    order = ["critical", "high", "medium", "low", "info"]
    rows.sort(key=lambda f: order.index(f["severity"]) if f["severity"] in order else 9)
    out = [f"{len(rows)} open finding(s):"]
    for f in rows[:40]:
        out.append(f"- [{f['severity']}] {f['title']} ({f['check_id']}) on {f.get('component') or f.get('target_url')}"
                   + (f"\n    Fix: {f['recommendation']}" if f.get("recommendation") else ""))
    return "\n".join(out)


def scan_dependencies(client: httpx.Client, args: dict[str, Any]) -> str:
    bp = _call(client, "POST", "/api/ingest", json={"source": args["repo"]})
    scan = bp.get("dependency_scan")
    if not scan:
        return "Dependency scanning is off on this server (DEPENDENCY_SCAN=false)."
    if scan.get("error"):
        return scan["error"]
    lines = [f"{scan['vulnerable']} of {scan['checked']} pinned packages have known vulnerabilities."]
    for a in scan["advisories"][:40]:
        fix = f"fixed in {a['fixed_in']}" if a.get("fixed_in") else "no fix yet"
        lines.append(f"- [{a['severity']}] {a['package']} {a['version']} ({', '.join(a['cves']) or a['id']}), {fix}: "
                     f"{a['summary'][:140]}")
    return "\n".join(lines)


def get_fix_patch(client: httpx.Client, args: dict[str, Any]) -> str:
    body = {"target_url": args["target_url"], **({"repo": args["repo"]} if args.get("repo") else {})}
    patch = _call(client, "POST", "/api/security/patches", json=body)
    manual = "".join(f"\n- {m['check_id']}: {m['reason']}" for m in patch.get("manual") or [])
    return (f"Fix patch #{patch['id']} for {patch['repo']} (apply with `git apply`):\n\n{patch['patch']}"
            + (f"\nStill needs a change by hand:{manual}" if manual else ""))


TOOLS: dict[str, tuple[Callable[..., str], dict[str, Any]]] = {
    "test_site": (test_site, {
        "description": "Run TestSphere's full loop on a live URL: analyze the page, plan and run browser tests "
                       "(self-healing broken locators), passive security scan, report. Waits for the result.",
        "inputSchema": {"type": "object", "required": ["url"], "properties": {
            "url": {"type": "string", "description": "Live URL to test, e.g. http://localhost:3000/login"},
            "goal": {"type": "string", "description": "What to test in plain words, e.g. 'log in as ann with password pw "
                                                       "and add the backpack to the cart'"},
            "repo_url": {"type": "string", "description": "Public Git repository of the app (optional)"},
            "wait": {"type": "boolean", "description": "Wait for the result (default true)"}}}}),
    "get_run": (get_run, {
        "description": "The result of a TestSphere pipeline run: stages, failed tests with errors, findings.",
        "inputSchema": {"type": "object", "required": ["run_id"], "properties": {"run_id": {"type": "integer"}}}}),
    "list_findings": (list_findings, {
        "description": "Open security findings (headers, cookies, CORS, TLS, vulnerable dependencies) with fixes.",
        "inputSchema": {"type": "object", "properties": {"target_url": {"type": "string"}}}}),
    "scan_dependencies": (scan_dependencies, {
        "description": "Check a repository's pinned dependencies against known vulnerabilities (OSV.dev).",
        "inputSchema": {"type": "object", "required": ["repo"], "properties": {
            "repo": {"type": "string", "description": "https Git URL (or a local folder on a development server)"}}}}),
    "get_fix_patch": (get_fix_patch, {
        "description": "A git patch fixing the open security findings of a site in its repository's own code.",
        "inputSchema": {"type": "object", "required": ["target_url"], "properties": {
            "target_url": {"type": "string"}, "repo": {"type": "string"}}}}),
}


# ── JSON-RPC over stdio ────────────────────────────────────────────────────

def handle(message: dict[str, Any], client: httpx.Client) -> dict[str, Any] | None:
    """The reply to one JSON-RPC message (None for notifications)."""
    method, msg_id = message.get("method"), message.get("id")
    if msg_id is None:
        return None  # notifications/initialized, cancellations...

    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion")
        return ok({"protocolVersion": asked or PROTOCOL_VERSION, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO,
                   "instructions": "Use test_site after changing a web app to check it end to end; "
                                   "list_findings and get_fix_patch for security fixes."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": name, **spec} for name, (_, spec) in TOOLS.items()]})
    if method == "tools/call":
        params = message.get("params") or {}
        tool = TOOLS.get(params.get("name", ""))
        if tool is None:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32602, "message": f"Unknown tool {params.get('name')!r}"}}
        try:
            text, is_error = tool[0](client, params.get("arguments") or {}), False
        except (ToolError, KeyError, ValueError, TypeError) as exc:
            text, is_error = (str(exc) if isinstance(exc, ToolError) else f"Bad arguments: {exc}"), True
        return ok({"content": [{"type": "text", "text": text}], "isError": is_error})
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def serve(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout, client: httpx.Client | None = None) -> None:
    client = client or _api()
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = handle(message, client) if isinstance(message, dict) else \
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
