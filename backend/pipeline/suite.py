"""
TestSphere-AI — Test suite planning for the automated pipeline.

Turns one live page analysis (``URLAnalyzerService``) and, when the project
has an ingested codebase, its HTTP routes into a suite of browser tests:

- smoke        page loads, title and body render
- interaction  fill the discovered inputs and press the primary button
               (or the user's "what to test" scenario)
- content      the main heading is on the page
- link-*       same-site pages linked from the target render; the first few
               are analyzed too, and also check their title, heading and
               form controls (never submitting a form the goal did not ask for)
- route-*      GET routes found in the codebase, the same way

Steps use the same shape as ``URLAnalyzerService._synthesize_test_steps`` so
the orchestrator can run them unchanged.  Pure functions; the runner does the
network checks (which candidate pages actually load).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

MAX_LINK_PAGES = 3
MAX_ROUTE_PAGES = 5

# Never visit links that change state just by being opened
_UNSAFE_LINK = re.compile(r"log-?out|sign-?out|delete|remove|unsubscribe|destroy", re.IGNORECASE)
# Route paths with parameters or patterns cannot be visited as-is
_PARAM_PATH = re.compile(r"[{}<>:*()\[\]$^|?\\]")


def _step(n: int, action: str, *, target: str | None = None, value: str | None = None, description: str) -> dict[str, Any]:
    return {"step_number": n, "action": action, "target": target, "value": value, "description": description}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "root"


def _normalize(url: str) -> str:
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", p.query, ""))


def _clean_title(title: str) -> str:
    return (title.split(" - ")[0].split("|")[0].strip() or title)[:30]


def page_tests(analysis: dict[str, Any], prompt: str | None = None) -> list[dict[str, Any]]:
    """Tests for the analyzed page itself."""
    url = analysis["url"]
    title = analysis.get("page_title") or ""
    inventory = analysis.get("elements_inventory") or {}
    tests: list[dict[str, Any]] = []

    smoke = [_step(1, "NAVIGATE", value=url, description=f"Open {url}")]
    if title and not title.endswith(" Webpage"):  # analyzer's fallback when there is no <title>
        smoke.append(_step(2, "ASSERT_CONTAINS_TEXT", target="head > title", value=_clean_title(title),
                           description=f"Page title contains '{_clean_title(title)}'"))
    smoke.append(_step(len(smoke) + 1, "ASSERT_VISIBLE", target="body", description="Page body renders"))
    tests.append({"slug": "smoke", "name": f"Smoke: {title[:50] or url}", "category": "smoke", "steps": smoke})

    synthesized = (analysis.get("synthesized_test_case") or {}).get("steps") or []
    if any(str(s.get("action", "")).upper() in ("FILL", "CLICK", "PRESS") for s in synthesized):
        name = f"Scenario: {prompt.strip()[:60]}" if prompt and prompt.strip() else f"Interaction: {title[:50] or url}"
        tests.append({"slug": "interaction", "name": name, "category": "functional", "steps": synthesized})

    headings = inventory.get("headings") or []
    if headings:
        heading = headings[0][:40]
        tests.append({
            "slug": "content",
            "name": f"Content: heading '{heading}'",
            "category": "content",
            "steps": [
                _step(1, "NAVIGATE", value=url, description=f"Open {url}"),
                _step(2, "ASSERT_CONTAINS_TEXT", target="body", value=heading, description=f"Page shows '{heading}'"),
            ],
        })
    return tests


def candidate_pages(analysis: dict[str, Any], blueprint: dict[str, Any] | None = None, *,
                    link_limit: int = MAX_LINK_PAGES, route_limit: int = MAX_ROUTE_PAGES) -> list[dict[str, str]]:
    """Other same-site pages worth a render check: linked pages, then codebase GET routes.

    Returns ``{"kind": "link"|"route", "url", "label"}`` items, de-duplicated,
    excluding the analyzed page itself and links that look state-changing.
    """
    base = analysis["url"]
    origin = urlparse(base)
    seen = {_normalize(base)}
    out: list[dict[str, str]] = []

    def add(kind: str, url: str, label: str, limit: int) -> None:
        if sum(1 for c in out if c["kind"] == kind) >= limit:
            return
        p = urlparse(url)
        if p.scheme not in ("http", "https") or p.netloc.lower() != origin.netloc.lower():
            return
        key = _normalize(url)
        if key in seen or _UNSAFE_LINK.search(p.path):
            return
        seen.add(key)
        out.append({"kind": kind, "url": url, "label": label})

    for href in (analysis.get("elements_inventory") or {}).get("links") or []:
        href = href.strip()
        if not href or href.lower().startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        absolute = urljoin(base, href)
        add("link", absolute, urlparse(absolute).path or "/", link_limit)

    root = f"{origin.scheme}://{origin.netloc}"
    for route in _get_routes(blueprint):
        add("route", root + route, f"GET {route}", route_limit)
    return out


def _get_routes(blueprint: dict[str, Any] | None) -> Iterable[str]:
    for route in (blueprint or {}).get("routes") or []:
        method = str(route.get("method", "")).upper()
        path = str(route.get("path", ""))
        if method not in ("GET", "ANY", "*", "ALL") or not path.startswith("/") or _PARAM_PATH.search(path):
            continue
        if path == "/api" or path.startswith("/api/"):
            continue  # an API answers data, not a page to render
        yield path


_NO_FIELD = ("hidden", "submit", "button", "image", "reset")


def page_check_test(candidate: dict[str, str], page: dict[str, Any]) -> dict[str, Any]:
    """A linked or route page checked from its own analysis: it opens, shows
    its title and main heading, and its form controls are there.  Nothing is
    filled in or submitted: that page's form could send mail or change data."""
    test = render_test(candidate)
    url, title = candidate["url"], page.get("page_title") or ""
    inventory = page.get("elements_inventory") or {}
    steps = [_step(1, "NAVIGATE", value=url, description=f"Open {url}")]
    if title and not title.endswith(" Webpage"):
        steps.append(_step(len(steps) + 1, "ASSERT_CONTAINS_TEXT", target="head > title", value=_clean_title(title),
                           description=f"Page title contains '{_clean_title(title)}'"))
    headings = inventory.get("headings") or []
    if headings:
        steps.append(_step(len(steps) + 1, "ASSERT_CONTAINS_TEXT", target="body", value=headings[0][:40],
                           description=f"Page shows '{headings[0][:40]}'"))
    field = next((i for i in inventory.get("inputs") or [] if i.get("type", "text") not in _NO_FIELD), None)
    if field:
        steps.append(_step(len(steps) + 1, "ASSERT_VISIBLE", target=field["selector"],
                           description=f"The {(field.get('placeholder') or field.get('name') or 'input')[:40]} field is there"))
    button = next((b for b in inventory.get("buttons") or [] if b.get("selector") not in (None, "button")), None)
    if button:
        steps.append(_step(len(steps) + 1, "ASSERT_VISIBLE", target=button["selector"],
                           description=f"The '{(button.get('text') or 'button')[:40]}' button is there"))
    if len(steps) == 1:
        steps.append(_step(2, "ASSERT_VISIBLE", target="body", description="Page body renders"))
    return {**test, "steps": steps}


def render_test(candidate: dict[str, str]) -> dict[str, Any]:
    kind, url, label = candidate["kind"], candidate["url"], candidate["label"]
    return {
        "slug": f"{kind}-{_slug(urlparse(url).path)}",
        "name": f"{'Linked page' if kind == 'link' else 'Code route'}: {label}",
        "category": kind,
        "steps": [
            _step(1, "NAVIGATE", value=url, description=f"Open {url}"),
            _step(2, "ASSERT_VISIBLE", target="body", description="Page body renders"),
        ],
    }
