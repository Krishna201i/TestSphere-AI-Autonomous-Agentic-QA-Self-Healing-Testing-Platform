"""
TestSphere-AI — Test suite planning for the automated pipeline.

Turns one live page analysis (``URLAnalyzerService``) and, when the project
has an ingested codebase, its HTTP routes into a suite of browser tests:

- smoke        page loads, title and body render
- interaction  fill the discovered inputs and press the primary button
               (or the user's "what to test" scenario)
- content      the main heading is on the page
- link-*       same-site pages linked from the target render
- route-*      GET routes found in the codebase render on the live site

Steps use the same shape as ``URLAnalyzerService._synthesize_test_steps`` so
the orchestrator can run them unchanged.  Pure functions; the runner does the
network checks (which candidate pages actually load).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse, urlunparse

MAX_LINK_PAGES = 3
MAX_ROUTE_PAGES = 5

# Never visit links that change state just by being opened
_UNSAFE_LINK = re.compile(r"log-?out|sign-?out|delete|remove|unsubscribe|destroy", re.IGNORECASE)
# Route paths with parameters or patterns cannot be visited as-is
_PARAM_PATH = re.compile(r"[{}<>:*()\[\]$^|?\\]")


def _step(n: int, action: str, *, target: Optional[str] = None, value: Optional[str] = None, description: str) -> Dict[str, Any]:
    return {"step_number": n, "action": action, "target": target, "value": value, "description": description}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "root"


def _normalize(url: str) -> str:
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", p.query, ""))


def _clean_title(title: str) -> str:
    return (title.split(" - ")[0].split("|")[0].strip() or title)[:30]


def page_tests(analysis: Dict[str, Any], prompt: Optional[str] = None) -> List[Dict[str, Any]]:
    """Tests for the analyzed page itself."""
    url = analysis["url"]
    title = analysis.get("page_title") or ""
    inventory = analysis.get("elements_inventory") or {}
    tests: List[Dict[str, Any]] = []

    smoke = [_step(1, "NAVIGATE", value=url, description=f"Open {url}")]
    if title and not title.endswith(" Webpage"):  # analyzer's fallback when there is no <title>
        smoke.append(_step(2, "ASSERT_CONTAINS_TEXT", target="head > title", value=_clean_title(title),
                           description=f"Page title contains '{_clean_title(title)}'"))
    smoke.append(_step(len(smoke) + 1, "ASSERT_VISIBLE", target="body", description="Page body renders"))
    tests.append({"slug": "smoke", "name": f"Smoke: {title[:50] or url}", "category": "smoke", "steps": smoke})

    synthesized = (analysis.get("synthesized_test_case") or {}).get("steps") or []
    if any(str(s.get("action", "")).upper() in ("FILL", "CLICK") for s in synthesized):
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


def candidate_pages(analysis: Dict[str, Any], blueprint: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """Other same-site pages worth a render check: linked pages, then codebase GET routes.

    Returns ``{"kind": "link"|"route", "url", "label"}`` items, de-duplicated,
    excluding the analyzed page itself and links that look state-changing.
    """
    base = analysis["url"]
    origin = urlparse(base)
    seen = {_normalize(base)}
    out: List[Dict[str, str]] = []

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
        add("link", absolute, urlparse(absolute).path or "/", MAX_LINK_PAGES)

    root = f"{origin.scheme}://{origin.netloc}"
    for route in _get_routes(blueprint):
        add("route", root + route, f"GET {route}", MAX_ROUTE_PAGES)
    return out


def _get_routes(blueprint: Optional[Dict[str, Any]]) -> Iterable[str]:
    for route in (blueprint or {}).get("routes") or []:
        method = str(route.get("method", "")).upper()
        path = str(route.get("path", ""))
        if method not in ("GET", "ANY", "*", "ALL") or not path.startswith("/") or _PARAM_PATH.search(path):
            continue
        yield path


def render_test(candidate: Dict[str, str]) -> Dict[str, Any]:
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
