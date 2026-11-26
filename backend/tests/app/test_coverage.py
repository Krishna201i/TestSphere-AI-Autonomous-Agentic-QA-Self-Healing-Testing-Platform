"""
The coverage suite (app/pipeline/coverage.py): a test per heading, field,
button, link and image, planned from the analysis alone, and, in real
Chromium, passing on the page it was planned from and failing once that page
loses what the test protects (never self-healing onto a look-alike).
"""

from __future__ import annotations

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agents.planner.schemas import TestCase as Member1TestCase
from app.orchestration.converters import test_case_to_engine_plan as to_engine_plan
from app.orchestration.orchestrator import parse_stored_steps
from app.pipeline import coverage
from app.pipeline.profile import COVERAGE_TYPES, GenerationProfile, profile_of, select
from app.services.url_analyzer import URLAnalyzerService as U
from engine.runner import run_test
from engine.schemas import RunOptions, TestStatus

HOME = """<!doctype html><html lang="en"><head><title>Acme Store</title></head><body>
<h1>Acme Store</h1><h2>New arrivals</h2><h2>Customer favourites</h2>
<nav><a href="/about">About us</a> <a href="/logout">Log out</a> <a href="https://elsewhere.example/">Partner</a>
<a href="/files/catalog.pdf">Catalog</a></nav>
<img src="/logo.png" alt="Acme logo" width="40" height="40">
<form action="/subscribe">
  <input id="email" name="email" type="email" required aria-label="Email address" placeholder="you@example.com">
  <input id="nick" name="nick" maxlength="12" placeholder="Nickname">
  <select id="size" name="size"><option value="">Choose…</option><option value="s">Small</option><option value="m">Medium</option></select>
  <input id="news" name="news" type="checkbox">
  <button id="join" type="submit">Join the list</button>
</form></body></html>"""
# The same page after a careless release: nothing required, the email field is
# plain text, no length limit, the logo lost its alt text, no page language
BROKEN = (HOME.replace(' lang="en"', "").replace(" required", "").replace('type="email"', 'type="text"')
          .replace(' maxlength="12"', "").replace('alt="Acme logo"', 'alt=""'))
ABOUT = """<!doctype html><html lang="en"><title>About Acme</title><h1>About Acme</h1><h2>Our story</h2>
<a href="/">Home</a></html>"""
# A release whose phone layout hides the product sections
NARROW_BROKEN = HOME.replace("<h2>New arrivals</h2>", '<style>@media (max-width: 600px) { .wide { display: none } }</style>'
                             '<h2 class="wide">New arrivals</h2>')
PAGES = {"/": HOME, "/broken": BROKEN, "/about": ABOUT, "/logo.png": "", "/narrow-broken": NARROW_BROKEN}
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def analysis_of(url: str, html: str, *, visible: bool = True) -> dict:
    """An analysis as ``analyze_live_website`` returns it, from the page's HTML."""
    title = re.search(r"<title>(.*?)</title>", html)
    lang = re.search(r'<html[^>]*lang="([^"]+)"', html)
    return {
        "url": url, "page_title": title.group(1) if title else "", "visibility_checked": visible,
        "page_lang": lang.group(1) if lang else None,
        "elements_inventory": {
            "inputs": U._extract_inputs(html), "buttons": U._extract_buttons(html),
            "headings": U._extract_headings(html), "links": U._extract_links(html, "x"),
            "link_details": U._extract_link_details(html), "images": U._extract_images(html),
        },
    }


@pytest.fixture(scope="module")
def site():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            path = self.path.split("?")[0]
            self.send_response(200 if path in PAGES else 404)
            self.send_header("Content-Type", "image/png" if path.endswith(".png") else "text/html")
            self.end_headers()
            self.wfile.write(PNG if path.endswith(".png") else PAGES.get(path, "<p>404</p>").encode())

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def plan(base: str = "http://shop.test") -> list[dict]:
    return coverage.site_coverage(base + "/", analysis_of(base + "/", HOME),
                                  {base + "/about": analysis_of(base + "/about", ABOUT)})


def by_kind(tests: list[dict], kind: str) -> list[dict]:
    return [t for t in tests if t["slug"].startswith(f"cov-{kind}-")]


# ── planning ───────────────────────────────────────────────────


def test_every_kind_is_planned_with_unique_stable_slugs():
    tests = plan()
    assert {t["category"] for t in tests} == {"content", "elements", "validation", "navigation", "accessibility", "responsive"}
    assert len({t["slug"] for t in tests}) == len(tests)
    assert [t["slug"] for t in plan()] == [t["slug"] for t in tests]  # same page, same rows next run
    assert all(t["steps"][0]["action"] == "NAVIGATE" for t in tests)
    assert all(any(s["action"].startswith("ASSERT") for s in t["steps"]) for t in tests)
    names = {t["name"] for t in tests}
    assert "Heading 'New arrivals' is shown · /" in names
    assert "Heading 'Acme Store' is shown · /" not in names  # the core content test checks the first heading
    assert "Field 'Email address' is still required · /" in names
    assert "Field 'Email address' is still a email field · /" in names
    assert "Field 'Nickname' is limited to 12 characters · /" in names
    assert "Dropdown 'size' can select 's' · /" in names
    assert "Checkbox 'news' can be ticked and cleared · /" in names
    assert "Button 'Join the list' is shown with its label · /" in names
    assert "Clicking 'About us' opens /about · /" in names
    assert "Page declares its language (en) · /" in names
    assert "Image 'Acme logo' is shown with its alt text · /" in names
    assert "Back from /about returns to this page · /" in names
    assert "Heading 'Our story' is shown · /about" in names
    assert "Page shows its content on a phone (390 px wide) · /" in names
    assert {t["viewport"] for t in tests if t["category"] == "responsive"} == {"390x844", "768x1024"}


def test_the_shared_header_and_footer_are_checked_once_not_on_every_page():
    base = "http://shop.test"
    nav = '<a href="/a">A</a><a href="/b">B</a><h3>Company</h3>'
    pages = {f"{base}/p{i}": analysis_of(f"{base}/p{i}", f"<html><h1>Page {i}</h1>{nav}<h2>Own {i}</h2></html>") for i in range(5)}
    tests = coverage.site_coverage(base + "/", analysis_of(base + "/", f"<html><h1>Home</h1>{nav}</html>"), pages)
    assert len(by_kind(tests, "link")) == 2                       # /a and /b, once
    assert sum(1 for t in tests if t["name"].startswith("Heading 'Company'")) == 1
    assert len([t for t in by_kind(tests, "heading") if "Own" in t["name"]]) == 5  # each page's own content still is


def test_it_never_presses_a_button_or_clicks_an_unsafe_external_or_file_link():
    tests = plan()
    clicked = [s["target"] for t in tests for s in t["steps"] if s["action"] == "CLICK"]
    assert clicked == ['a[href="/about"]:visible']  # not /logout, the partner site, the PDF, or "Join"
    assert not any(s["action"] in ("PRESS", "SUBMIT") for t in tests for s in t["steps"])


def test_a_page_read_without_a_browser_gets_quarantined_tests():
    base = "http://shop.test/"
    tests = coverage.site_coverage(base, analysis_of(base, HOME, visible=False), {})
    assert tests and all(t["quarantined"] for t in tests)
    assert not any(t["quarantined"] for t in plan())


def test_interleaving_keeps_every_kind_when_the_list_is_cut():
    assert {t["category"] for t in plan()[:len(coverage.CATEGORIES)]} == set(coverage.CATEGORIES)


def test_per_page_limits_hold_on_a_huge_page():
    links = "".join(f'<a href="/p{i}">Page {i}</a>' for i in range(200))
    heads = "".join(f"<h2>Section {i}</h2>" for i in range(100))
    html = f"<html><h1>Big</h1>{heads}{links}</html>"
    tests = coverage.page_coverage("http://big.test/", analysis_of("http://big.test/", html),
                                   start=True, safe_paths={f"/p{i}" for i in range(200)})
    assert len(by_kind(tests, "heading")) == coverage.MAX_HEADINGS
    assert len(by_kind(tests, "link")) == coverage.MAX_LINKS_SHOWN
    assert len(by_kind(tests, "click")) == coverage.MAX_LINK_CLICKS


def test_a_content_rich_site_reaches_hundreds_of_tests():
    def page(n: int) -> str:
        return ("<html lang='en'><h1>Page</h1>" + "".join(f"<h2>Topic {n}-{i}</h2>" for i in range(15))
                + "".join(f'<a href="/p{i}">Go {i}</a>' for i in range(12))
                + "".join(f'<img src="/i{n}-{i}.png" alt="Picture {i}">' for i in range(6)) + "</html>")
    pages = {f"http://rich.test/p{i}": analysis_of(f"http://rich.test/p{i}", page(i)) for i in range(10)}
    tests = coverage.site_coverage("http://rich.test/", analysis_of("http://rich.test/", page(99)), pages)
    assert len(tests) >= 250


# ── the generation profile ─────────────────────────────────────


def test_profiles_choose_coverage_kinds_and_old_profiles_get_them():
    tests = plan()
    only_nav = GenerationProfile(test_types=["navigation"])
    assert {t["category"] for t in select(tests, only_nav)} == {"navigation"}
    # Saved before the coverage kinds existed: they were never declined
    legacy = profile_of({"generation_profile": {"test_types": ["smoke", "content"]}})
    assert set(COVERAGE_TYPES) <= set(legacy.test_types)
    # Saved now: exactly what was chosen
    chosen = profile_of({"generation_profile": {"test_types": ["smoke"], "version": 2}})
    assert chosen.test_types == ["smoke"]


# ── in real Chromium ───────────────────────────────────────────


async def _run(test: dict, url: str) -> TestStatus:
    steps, assertions = parse_stored_steps(test["steps"], url)
    case = Member1TestCase(test_id=test["slug"], name=test["name"], page_url=url, steps=steps, assertions=assertions)
    options = RunOptions(min_action_timeout_ms=1500, viewport=test.get("viewport"))
    return (await run_test(to_engine_plan(case, url), options)).status


async def test_every_planned_test_passes_on_the_page_it_was_planned_from(site):
    tests = coverage.site_coverage(site + "/", analysis_of(site + "/", HOME),
                                   {site + "/about": analysis_of(site + "/about", ABOUT)})
    for test in tests:
        assert await _run(test, site + "/") == TestStatus.PASSED, test["name"]


@pytest.mark.parametrize("kind", ["required", "type", "maxlength", "lang", "image"])
async def test_a_dropped_attribute_fails_the_test_instead_of_healing(site, kind):
    tests = by_kind(coverage.site_coverage(site + "/", analysis_of(site + "/", HOME), {}), kind)
    assert tests, kind
    for test in tests:
        broken = {**test, "steps": [{**s, "value": site + "/broken"} if s["action"] == "NAVIGATE" else s
                                    for s in test["steps"]]}
        assert await _run(broken, site + "/broken") == TestStatus.FAILED, test["name"]


async def test_a_layout_that_hides_content_on_phones_fails_the_phone_check(site):
    phone = next(t for t in coverage.site_coverage(site + "/", analysis_of(site + "/", HOME), {})
                 if t["slug"].startswith("cov-phone-"))
    assert await _run(phone, site + "/") == TestStatus.PASSED
    hidden = {**phone, "steps": [{**s, "value": site + "/narrow-broken"} if s["action"] == "NAVIGATE" else s
                                 for s in phone["steps"]]}
    assert await _run(hidden, site + "/narrow-broken") == TestStatus.FAILED
    # The same page is fine on a desktop: only the phone layout hides it
    assert await _run({**hidden, "viewport": None}, site + "/narrow-broken") == TestStatus.PASSED


# ── the second hop ─────────────────────────────────────────────


def test_a_second_hop_finds_pages_linked_only_from_inner_pages(monkeypatch):
    import asyncio

    from app.config import settings
    from app.pipeline import runner

    monkeypatch.setattr(settings, "PIPELINE_DEEP_PAGES", 3)
    monkeypatch.setattr(settings, "PIPELINE_LINK_PAGES", 10)

    async def reachable(urls):
        return {u: {"status": 404 if "gone" in u else 200, "file": u.endswith(".csv"), "digest": u} for u in urls}

    monkeypatch.setattr(runner, "_reachable", reachable)
    start = {"url": "http://s.test/", "elements_inventory": {"links": ["/blog"]}}
    candidates = [{"kind": "link", "url": "http://s.test/blog", "label": "/blog"}]
    blog = {"url": "http://s.test/blog", "final_url": "http://s.test/blog",
            "elements_inventory": {"links": ["/blog/1", "/", "/blog", "/logout", "/gone", "/data.csv", "/blog/2", "/blog/3"]}}
    hop, left_out = asyncio.run(runner._second_hop(start, candidates, {"http://s.test/blog": blog}))
    # Room for 2 more analyzed pages (3 - the 1 already analyzed): never past the limit
    assert [c["url"] for c in hop] == ["http://s.test/blog/1", "http://s.test/blog/2"]
    assert left_out == ["/gone (404)"]  # a page that did not load is said, not tested
    # The start page and pages already known are not found again; a log-out link is never followed
    assert all(c["url"] not in ("http://s.test/", "http://s.test/blog", "http://s.test/logout") for c in hop)


# ── what a real site taught: changing text, script markup, signed-in pages ──


def _http_reads(monkeypatch, bodies):
    """get_verifying_first answers each URL with the next of its bodies."""
    from types import SimpleNamespace

    from app.pipeline import runner

    served = {u: iter(b) for u, b in bodies.items()}
    sent = []

    async def fetch(url, headers=None, **_):
        sent.append((url, (headers or {}).get("Cookie")))
        return SimpleNamespace(text=next(served[url])), True

    monkeypatch.setattr(runner, "get_verifying_first", fetch)
    return sent


def test_headings_that_change_between_visits_are_never_checked(monkeypatch):
    import asyncio

    from app.pipeline import runner, suite

    ab = {"url": "http://s.test/ab", "elements_inventory": {"headings": ["A/B Test Control", "Shared"]}}
    swapped = {"url": "http://s.test/sw", "elements_inventory": {"headings": ["Variant A"]}}
    scripted = {"url": "http://s.test/js", "elements_inventory": {"headings": ["Server title", "Added by script"]}}
    built = {"url": "http://s.test/spa", "elements_inventory": {"headings": ["Rendered"]}}
    _http_reads(monkeypatch, {
        ab["url"]: ["<h1>Variation 1</h1><h2>Shared</h2>", "<h1>A/B Test Control</h1><h2>Shared</h2>",
                    "<h1>Variation 1</h1><h2>Shared</h2>"],               # reads differ
        swapped["url"]: ["<h1>Variant B</h1>"] * 3,                      # always the same, but not what analysis saw
        scripted["url"]: ["<h1>Server title</h1>"] * 3,                  # scripts add one: no reason
        built["url"]: ["<div id=root></div>"] * 3,                       # built by scripts: cannot judge
    })
    marked = asyncio.run(runner._mark_changing_text([ab, swapped, scripted, built]))
    assert ab["changing_text"] == ["A/B Test Control"] and swapped["changing_text"] == ["Variant A"]
    assert "changing_text" not in scripted and "changing_text" not in built and marked == 2
    assert suite.stable_headings(ab) == ["Shared"]
    names = [t["name"] for t in coverage.page_coverage("http://s.test/ab", {**ab, "visibility_checked": True},
                                                       start=False, safe_paths=set())]
    assert not any("A/B Test Control" in n for n in names)


def test_pages_read_signed_in_are_re_read_with_the_session_and_judged_only_by_disagreeing(monkeypatch):
    import asyncio

    from app.pipeline import runner

    session = {"cookies": [{"name": "sid", "value": "abc", "domain": "s.test"},
                           {"name": "other", "value": "x", "domain": "elsewhere.test"}]}
    ab = {"url": "http://s.test/ab", "signed_in": True, "elements_inventory": {"headings": ["Control"]}}
    # Not let in: the same sign-in page every time, nothing like the analysis. Proves nothing
    locked = {"url": "http://s.test/orders", "signed_in": True, "elements_inventory": {"headings": ["Your orders"]}}
    sent = _http_reads(monkeypatch, {ab["url"]: ["<h1>Control</h1>", "<h1>Variation 1</h1>", "<h1>Control</h1>"],
                                     locked["url"]: ["<h1>Sign in</h1>"] * 3})
    assert asyncio.run(runner._mark_changing_text([ab, locked], session)) == 1
    assert ab["changing_text"] == ["Control"] and "changing_text" not in locked
    assert {cookie for _, cookie in sent} == {"sid=abc"}  # only this site's cookies


def test_markup_inside_scripts_and_templates_is_not_on_the_page():
    from app.services.url_analyzer import visible_markup

    html = ('<h1>Real</h1><script>var s = "<input id=closed-input><h2>Fake</h2>";</script>'
            '<template shadowrootmode="closed"><input id="t"></template><input id="ok" name="ok">')
    assert U._extract_headings(visible_markup(html)) == ["Real"]
    assert [f["selector"] for f in U._extract_inputs(visible_markup(html))] == ["#ok"]


def test_with_sign_in_first_the_pages_behind_the_login_are_analyzed_and_covered_signed_in(fresh_store, monkeypatch):
    import asyncio
    import json

    from app.models import TEST_CASES
    from app.pipeline import runner
    from app.services.project_service import ProjectService

    base = "http://app.test"
    login = {**analysis_of(base + "/login", "<html><h1>Sign in</h1><a href='/help'>Help</a></html>"),
             "success": True, "status_code": 200, "latency_ms": 1,
             "synthesized_test_case": {"steps": [{"step_number": 1, "action": "FILL", "target": "#u", "value": "a",
                                                  "description": "fill"},
                                                 {"step_number": 2, "action": "CLICK", "target": "#go", "description": "go"}]}}
    dash = {**analysis_of(base + "/dashboard", "<html lang='en'><h1>Dashboard</h1><h2>Your orders</h2></html>"),
            "final_url": base + "/dashboard", "signed_in": True}
    sessions = []

    async def sign_in(tests, url):
        return {"cookies": [{"name": "sid"}]}, base + "/dashboard"

    async def analyze(urls, session=None):
        sessions.append(session)
        return {u: dash for u in urls if u.endswith("/dashboard")}

    async def reachable(urls):
        return {u: {"status": 200, "file": False, "digest": u} for u in urls}

    async def nothing_changes(pages, session=None):
        return 0

    monkeypatch.setattr(runner, "_sign_in_session", sign_in)
    monkeypatch.setattr(runner, "_analyze_pages", analyze)
    monkeypatch.setattr(runner, "_reachable", reachable)
    monkeypatch.setattr(runner, "_mark_changing_text", nothing_changes)
    project = ProjectService.create_project(fresh_store, name="App", owner_uid="local-dev", app_url=base + "/login",
                                            sign_in_first=True, prompt="log in")
    _, tests, detail = asyncio.run(runner._plan(fresh_store, project, login, None))

    assert sessions and all(s == {"cookies": [{"name": "sid"}]} for s in sessions)  # read signed in
    assert "signed in while planning" in detail
    behind = [t for t in tests if json.loads(t["description"]).get("signed_in")]
    names = {t["name"] for t in behind}
    # The page signing in leads to was found though nothing links to it, and is covered
    assert "Heading 'Your orders' is shown · /dashboard" in names
    assert any(n.startswith("Linked page: /dashboard") for n in names)
    # Those tests start from the sign-in session; the sign-in page's own tests do not
    row = next(t for t in behind if t["name"].startswith("Heading 'Your orders'"))
    assert runner._signed_in_kwargs(fresh_store.get(TEST_CASES, row["id"]), True, [{"s": 1}]) == {"storage_state": {"s": 1}}
