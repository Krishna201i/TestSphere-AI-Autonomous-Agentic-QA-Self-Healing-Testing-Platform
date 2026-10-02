"""
engine/detector.py
==================
Element detection and DOM analysis for the TestSphere-AI engine.

Two public async functions:

``build_fingerprint(page, locator_str)``
    Capture an ``ElementFingerprint`` for the element matched by *locator_str*
    on the current page.  Called after every successful element interaction so
    the engine has a rich snapshot for future healing.

``extract_candidates(page, fingerprint, max_candidates)``
    Query the live DOM for elements that *could* be the target element, and
    return a list of Playwright locator strings for the healer to score.

Both functions are fault-tolerant: any exception is logged and a safe default
is returned (``None`` / ``[]``) so callers are never disrupted.
"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from .schemas import BoundingBox, ElementFingerprint

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JavaScript snippets (kept as module-level constants for testability)
# ---------------------------------------------------------------------------

# Runs inside the matched element's context via locator.evaluate()
_FINGERPRINT_JS = """\
(el) => {
    // Parent chain: nearest ancestor first, up to 5 levels
    const chain = [];
    let p = el.parentElement;
    while (p && p !== document.body && chain.length < 5) {
        const id  = p.id ? '#' + p.id : '';
        const cls = p.classList.length ? '.' + [...p.classList].join('.') : '';
        chain.push(p.tagName.toLowerCase() + id + cls);
        p = p.parentElement;
    }

    // 0-based index among same-tag siblings
    let sibIdx = null;
    if (el.parentElement) {
        const sibs = [...el.parentElement.children].filter(c => c.tagName === el.tagName);
        sibIdx = sibs.indexOf(el);
    }

    // All attributes except those captured in dedicated fields
    const SKIP = new Set(['id', 'class', 'role', 'aria-label', 'name', 'placeholder']);
    const attrs = {};
    for (const a of el.attributes) {
        if (!SKIP.has(a.name)) attrs[a.name] = a.value;
    }

    return {
        tag:          el.tagName.toLowerCase(),
        id:           el.id || null,
        classes:      [...el.classList],
        text:         (el.innerText || '').trim().slice(0, 200) || null,
        role:         el.getAttribute('role') || null,
        aria_label:   el.getAttribute('aria-label') || null,
        name:         el.getAttribute('name') || null,
        placeholder:  el.getAttribute('placeholder') || null,
        attributes:   attrs,
        parent_chain: chain,
        sibling_index: sibIdx,
    };
}
"""

# Runs at document level; returns a list of raw element descriptors
_CANDIDATES_JS = """\
([selectors, maxN]) => {
    const seen = new Set();
    const raw  = [];

    for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
            if (!seen.has(el)) {
                seen.add(el);
                raw.push({
                    tag:        el.tagName.toLowerCase(),
                    id:         el.id || null,
                    testid:     el.getAttribute('data-testid') || null,
                    aria_label: el.getAttribute('aria-label') || null,
                    name:       el.getAttribute('name') || null,
                    text:       (el.innerText || '').trim().slice(0, 80),
                    classes:    [...el.classList],
                });
            }
        }
        if (raw.length >= maxN * 3) break;
    }

    return raw.slice(0, maxN * 3);   // Python culls to maxN after building locators
}
"""

# Standard CSS selectors that catch almost all interactive elements
_INTERACTIVE_SELECTORS = [
    "button", "input", "a", "select", "textarea",
    "[role]", "[data-testid]", "[aria-label]",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def build_fingerprint(page: Page, locator_str: str) -> ElementFingerprint | None:
    """
    Capture a rich ``ElementFingerprint`` for the element matched by *locator_str*.

    Uses ``locator.evaluate()`` so any valid Playwright locator string (CSS,
    XPath, role selector, etc.) is accepted — not just ``querySelector``-
    compatible CSS.

    Parameters
    ----------
    page:
        The Playwright page on which to locate the element.
    locator_str:
        Any valid Playwright locator (``#id``, ``//xpath``, ``[role=...]``, …).

    Returns
    -------
    ElementFingerprint | None
        ``None`` if the element is not found or JS evaluation fails.
    """
    try:
        locator = page.locator(locator_str).first

        info: dict = await locator.evaluate(_FINGERPRINT_JS)

        bb_raw = await locator.bounding_box()
        bbox = BoundingBox(**bb_raw) if bb_raw else None

        return ElementFingerprint(
            tag=info["tag"],
            id=info["id"],
            classes=info["classes"],
            text=info["text"],
            role=info["role"],
            aria_label=info["aria_label"],
            name=info["name"],
            placeholder=info["placeholder"],
            attributes=info["attributes"],
            parent_chain=info["parent_chain"],
            sibling_index=info["sibling_index"],
            bounding_box=bbox,
        )

    except Exception as exc:
        log.warning("build_fingerprint failed for %r: %s", locator_str, exc)
        return None


async def extract_candidates(
    page: Page,
    fingerprint: ElementFingerprint,
    max_candidates: int = 20,
) -> list[str]:
    """
    Harvest Playwright locator strings for candidate elements in the live DOM.

    Queries the DOM for elements sharing the same tag as *fingerprint* plus all
    interactive elements (buttons, inputs, links, …).  Each candidate is
    represented by its most stable available locator (id > testid > aria-label >
    name > text > class), ready for the healer to score against *fingerprint*.

    Parameters
    ----------
    page:
        Live Playwright page to query.
    fingerprint:
        Fingerprint of the element we are looking for (used to determine the
        primary tag to search for).
    max_candidates:
        Upper bound on the returned list length.

    Returns
    -------
    list[str]
        Deduplicated Playwright locator strings, or ``[]`` on JS failure.
    """
    tag = fingerprint.tag or "button"
    selectors = list(dict.fromkeys([tag, *_INTERACTIVE_SELECTORS]))  # ordered-unique

    try:
        raw: list[dict] = await page.evaluate(_CANDIDATES_JS, [selectors, max_candidates])
    except Exception as exc:
        log.warning("extract_candidates JS evaluation failed: %s", exc)
        return []

    return _raw_to_locators(raw, max_candidates)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _raw_to_locators(raw: list[dict], limit: int) -> list[str]:
    """Convert JS-returned element descriptors into deduplicated locator strings."""
    seen: set[str] = set()
    result: list[str] = []

    for info in raw:
        loc = _best_locator(info)
        if loc and loc not in seen:
            seen.add(loc)
            result.append(loc)
            if len(result) >= limit:
                break

    return result


def _best_locator(info: dict) -> str | None:
    """
    Return the most stable Playwright locator for a raw element descriptor.

    Priority: id > data-testid > aria-label > name > text (XPath) > class.
    """
    tag = (info.get("tag") or "element").lower()

    if info.get("id"):
        return f'#{info["id"]}'
    if info.get("testid"):
        return f'[data-testid="{info["testid"]}"]'
    if info.get("aria_label"):
        al = info["aria_label"].replace('"', '\\"')
        return f'[aria-label="{al}"]'
    if info.get("name"):
        return f'{tag}[name="{info["name"]}"]'

    text = (info.get("text") or "").strip()
    if text:
        escaped = text.replace('"', '\\"')
        return f'//{tag}[contains(normalize-space(),"{escaped}")]'

    classes = info.get("classes") or []
    if classes:
        return f'{tag}.{classes[0]}'

    return None
