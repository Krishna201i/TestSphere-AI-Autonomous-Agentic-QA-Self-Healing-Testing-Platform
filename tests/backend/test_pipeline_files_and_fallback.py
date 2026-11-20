"""
Linked files and code routes on a host that answers every URL.

Measured on a real single-page app (a front end on Netlify with its API not
deployed): two sample-file links failed with "Download is starting" (a
browser cannot open a CSV as a page) and the code route GET /health passed,
because the host sent its home page for it with status 200.  Files are now
checked by request, and a route answered with the catch-all page is left
out as not served.
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.pipeline import runner, suite

INDEX = b"<!doctype html><title>App</title><h1>Welcome</h1>"


@pytest.fixture(scope="module")
def spa_host():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/samples/fleet.csv":
                body, kind = b"id,cpu\n1,20\n", "text/csv"
            elif self.path == "/samples/fleet.json":
                body, kind = b'{"ok": true}', "application/json"
            else:  # a single-page app's host: the index for every other path
                body, kind = INDEX, "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_files_are_told_from_pages_and_the_catch_all_is_recognised(spa_host):
    urls = [f"{spa_host}/samples/fleet.csv", f"{spa_host}/samples/fleet.json", f"{spa_host}/about", f"{spa_host}/health"]
    answers = asyncio.run(runner._reachable(urls))
    assert [answers[u]["file"] for u in urls] == [True, True, False, False]

    fallback = asyncio.run(runner._fallback_digests(spa_host + "/"))
    # /health is the same catch-all page; a real route would differ
    assert answers[f"{spa_host}/health"]["digest"] in fallback and answers[f"{spa_host}/about"]["digest"] in fallback


def test_a_real_route_is_not_mistaken_for_the_catch_all(spa_host):
    answers = asyncio.run(runner._reachable([f"{spa_host}/samples/fleet.json"]))
    assert answers[f"{spa_host}/samples/fleet.json"]["digest"] not in asyncio.run(runner._fallback_digests(spa_host + "/"))


def test_a_slow_probe_still_finds_the_catch_all(spa_host, monkeypatch):
    # The real run: the probe of a missing path timed out on a slow host's first answer.
    # The start page is compared too, and the probe is tried again.
    real, calls = runner._reachable, []

    async def first_probe_times_out(urls):
        calls.append(urls)
        found = await real(urls)
        if len(calls) == 1:
            found[urls[0]] = None
        return found

    monkeypatch.setattr(runner, "_reachable", first_probe_times_out)
    digests = asyncio.run(runner._fallback_digests(spa_host + "/"))
    assert len(calls) == 2
    monkeypatch.setattr(runner, "_reachable", real)
    assert asyncio.run(real([spa_host + "/health"]))[spa_host + "/health"]["digest"] in digests


def test_the_plan_checks_files_by_request_and_leaves_out_unserved_routes(fresh_store, spa_host, monkeypatch):
    from backend.services.project_service import ProjectService

    analysis = {"url": spa_host + "/", "page_title": "App", "success": True,
                "elements_inventory": {"links": ["/samples/fleet.csv", "/about"], "headings": [], "hidden_controls": 3},
                "synthesized_test_case": {"steps": []}}
    blueprint = {"routes": [{"method": "GET", "path": "/health"}]}
    project = ProjectService.create_project(fresh_store, name="SPA", owner_uid="local-dev", app_url=spa_host + "/")

    async def no_deep_analysis(urls):
        return {}

    monkeypatch.setattr(runner, "_analyze_pages", no_deep_analysis)
    _, tests, detail = asyncio.run(runner._plan(fresh_store, project, analysis, blueprint))

    names = {t["name"] for t in tests}
    assert "Linked page: /about" in names
    assert not any("fleet.csv" in n or "/health" in n for n in names)
    assert "GET /health (answers with the site's catch-all page: not served here)" in detail
    assert "1 file or data URL(s) answered fine" in detail and "/samples/fleet.csv" in detail
    assert "3 control(s) hidden on load" in detail
    assert {t["name"] for t in suite.page_tests(analysis)} == {"Smoke: App"}


def test_names_and_title_checks_are_cut_at_a_word():
    # Measured: "Smoke: CloudOptimizer — Autonomous Cloud Cost &amp; Perfo" and a check for 'CloudOptimizer — Autonomous Cl'
    title = "CloudOptimizer — Autonomous Cloud Cost & Performance Autopilot"
    smoke = suite.page_tests({"url": "https://x.example/", "page_title": title})[0]
    assert smoke["name"] == "Smoke: CloudOptimizer — Autonomous Cloud Cost"
    assert smoke["steps"][1]["value"] == "CloudOptimizer"  # the part before " — " (the tagline)
    assert suite._shorten("Short", 30) == "Short"
    assert suite._shorten("Supercalifragilisticexpialidocious", 10) == "Supercalif"  # one long word: hard cut
