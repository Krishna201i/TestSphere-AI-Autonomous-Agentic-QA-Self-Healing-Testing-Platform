"""
engine/locators.py
==================
Selector generation and stability ranking for the TestSphere-AI engine.

Two public functions:

``generate_locators(fp)``
    Given an ``ElementFingerprint``, produce a ranked list of Playwright
    locator strings ordered most-stable → least-stable:
    data-testid > role+name > id > aria > name/placeholder/text > CSS > XPath

``rank_locators(locators)``
    Sort an arbitrary list of locator strings by the same stability heuristic.
    Used to reorder ``Target.fallback_locators`` after detector enrichment.

No Playwright / browser imports — pure Python, fully unit-testable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from engine.schemas import ElementFingerprint

# An id usable as ``#id`` without escaping; anything else (React's ``:r1:``,
# ids with dots or starting with a digit) is written as ``[id="..."]``.
_SIMPLE_ID = re.compile(r"^[A-Za-z_][\w-]*$")


def css_string(value: str) -> str:
    """*value* as a double-quoted CSS string (backslashes and quotes escaped)."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def id_selector(element_id: str) -> str:
    """A valid selector for an element id, whatever characters it contains."""
    return f"#{element_id}" if _SIMPLE_ID.match(element_id) else f"[id={css_string(element_id)}]"


def xpath_string(value: str) -> str:
    """*value* as an XPath 1.0 string literal (which has no escape character)."""
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    return "concat(" + ", '\"', ".join(f'"{part}"' for part in value.split('"')) + ")"


def attr_selector(tag: str, attr: str, value: str) -> str:
    return f"{tag}[{attr}={css_string(value)}]"


def text_selector(tag: str, text: str) -> str:
    return f"{tag}:has-text({css_string(text[:80])})"


# What a candidate selector matches, so a page's own element list can count
# its matches without a browser: ("attr", tag or None, attribute, value) or
# ("text", tag, text) for Playwright's case-insensitive :has-text(), or
# ("text-is", tag, text) for its exact :text-is().
MatchKey = tuple


def stable_candidates(tag: str, attrs: dict[str, str | None], text: str | None = None) -> list[tuple[str, MatchKey]]:
    """Selectors for one element, most stable first, never by position or class,
    each with the key ``count_matches`` uses.

    The order the explorer uses: data-testid, id, name, aria-label,
    placeholder, then (inputs) the type and (buttons and links) the visible
    text.  Values are escaped, so any attribute value gives a valid selector.
    """
    out: list[tuple[str, MatchKey]] = []
    for key in ("data-testid", "data-test-id", "data-test"):
        if attrs.get(key):
            out.append((f"[{key}={css_string(attrs[key])}]", ("attr", None, key, attrs[key])))
            break
    if attrs.get("id"):
        out.append((id_selector(attrs["id"]), ("attr", None, "id", attrs["id"])))
    for attr in ("name", "aria-label", "placeholder"):
        if attrs.get(attr):
            out.append((attr_selector(tag, attr, attrs[attr]), ("attr", tag, attr, attrs[attr])))
    if tag == "input" and (attrs.get("type") or "").lower() in ("submit", "button") and attrs.get("value"):
        out.append((attr_selector("input", "value", attrs["value"]), ("attr", "input", "value", attrs["value"])))
    if tag in ("input", "textarea", "select") and attrs.get("type"):
        out.append((attr_selector(tag, "type", attrs["type"]), ("attr", tag, "type", attrs["type"])))
    if tag in ("button", "a") and text and text.strip():
        clean = " ".join(text.split())[:80]
        out.append((text_selector(tag, clean), ("text", tag, clean)))
        # Exact text: "Sign in" when "Sign in with Google" is also on the page
        out.append((f"{tag}:text-is({css_string(clean)})", ("text-is", tag, clean)))
    if tag == "button" and (attrs.get("type") or "").lower() == "submit":
        out.append(('button[type="submit"]', ("attr", "button", "type", attrs["type"])))
    return list({sel: (sel, key) for sel, key in out}.values())


def count_matches(key: MatchKey, elements: Iterable[tuple[str, dict[str, str | None], str]]) -> int:
    """How many of *elements* (tag, attributes, visible text) the key matches."""
    if key[0] in ("text", "text-is"):
        _, tag, text = key
        bodies = [" ".join((body or "").split()) for t, _, body in elements if t == tag]
        if key[0] == "text-is":
            return sum(1 for body in bodies if body == text)
        return sum(1 for body in bodies if text.lower() in body.lower())
    _, tag, attr, value = key
    return sum(1 for t, a, _ in elements if (tag is None or t == tag) and a.get(attr) == value)


def best_unique(candidates: Iterable[tuple[str, MatchKey]],
                elements: list[tuple[str, dict[str, str | None], str]]) -> str | None:
    """The first candidate selector matching exactly one of *elements*, else
    None: a selector matching several elements makes a test act on whichever
    comes first."""
    return next((sel for sel, key in candidates if count_matches(key, elements) == 1), None)


# ---------------------------------------------------------------------------
# Stability priority constants (lower = more stable)
# ---------------------------------------------------------------------------

_P_TESTID = 0   # data-testid / data-test-id
_P_ROLE = 1     # [role=...][aria-label=...] or [role=...]:has-text(...)
_P_ID = 2       # #element-id
_P_ARIA = 3     # [aria-label="..."] standalone
_P_ATTR = 4     # name / placeholder / :has-text() / type attribute
_P_CSS = 5      # tag.class, tag[attr], etc.
_P_XPATH = 6    # XPath — last resort


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_locators(fp: ElementFingerprint) -> list[str]:
    """
    Generate a stability-ranked list of Playwright locator strings from *fp*.

    Priority order (spec):
    data-testid > role+name > id > aria-label > name/placeholder/text > CSS > XPath

    The returned list is deduplicated and never contains empty strings.
    """
    candidates: list[tuple[int, str]] = []  # (priority_bucket, locator_string)
    tag = fp.tag or "*"

    # ---- 0: data-testid / data-test-id (most durable across refactors) ----
    dt = fp.attributes.get("data-testid") or fp.attributes.get("data-test-id")
    if dt:
        candidates.append((_P_TESTID, f"[data-testid={css_string(dt)}]"))

    # ---- 1: role + accessible name (ARIA-safe) ----------------------------
    if fp.role and fp.aria_label:
        candidates.append((_P_ROLE, f"[role={css_string(fp.role)}][aria-label={css_string(fp.aria_label)}]"))
    elif fp.role and fp.text:
        candidates.append((_P_ROLE, f"[role={css_string(fp.role)}]:has-text({css_string(fp.text[:80])})"))

    # ---- 2: id ------------------------------------------------------------
    if fp.id:
        candidates.append((_P_ID, id_selector(fp.id)))

    # ---- 3: aria-label standalone (even without role) ---------------------
    if fp.aria_label:
        candidates.append((_P_ARIA, f"[aria-label={css_string(fp.aria_label)}]"))

    # ---- 4: name / placeholder / visible text -----------------------------
    if fp.name:
        candidates.append((_P_ATTR, attr_selector(tag, "name", fp.name)))

    if fp.placeholder:
        candidates.append((_P_ATTR, f"[placeholder={css_string(fp.placeholder)}]"))

    if fp.text:
        candidates.append((_P_ATTR, text_selector(tag, fp.text)))

    # type attribute (button[type="submit"], input[type="email"], …)
    type_attr = fp.attributes.get("type")
    if type_attr:
        candidates.append((_P_ATTR, attr_selector(tag, "type", type_attr)))

    # ---- 5: CSS (classes, generic tag) ------------------------------------
    if fp.classes:
        # Only classes that are plain identifiers ("hover:bg-x" would need escaping)
        cls_str = "".join(f".{c}" for c in fp.classes if c and _SIMPLE_ID.match(c))
        if cls_str:
            candidates.append((_P_CSS, f"{tag}{cls_str}"))

    # ---- 6: XPath (last resort) -------------------------------------------
    if fp.id:
        candidates.append((_P_XPATH, f"//{tag}[@id={xpath_string(fp.id)}]"))
    elif fp.text:
        candidates.append((_P_XPATH, f"//{tag}[contains(normalize-space(),{xpath_string(fp.text[:80])})]"))
    else:
        candidates.append((_P_XPATH, f"//{tag}"))

    # Sort by priority then deduplicate (preserving first occurrence)
    candidates.sort(key=lambda x: x[0])
    seen: set[str] = set()
    result: list[str] = []
    for _, loc in candidates:
        if loc and loc not in seen:
            seen.add(loc)
            result.append(loc)

    return result


def rank_locators(locators: list[str]) -> list[str]:
    """
    Sort *locators* by estimated stability, most stable first.

    Uses a stable sort so equal-priority locators keep their relative order.
    Works on any Playwright locator strings (CSS, XPath, attribute selectors).
    """
    return sorted(locators, key=_locator_priority)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _locator_priority(loc: str) -> int:
    """Assign a numeric stability bucket to a locator string (lower = more stable)."""
    if "data-testid" in loc or "data-test-id" in loc:
        return _P_TESTID
    if loc.startswith("[role=") and ("[aria-label=" in loc or ":has-text(" in loc):
        return _P_ROLE
    if loc.startswith("#"):
        return _P_ID
    if loc.startswith("[aria-label="):
        return _P_ARIA
    if (
        ":has-text(" in loc
        or "[name=" in loc
        or "[placeholder=" in loc
        or "[type=" in loc
        or "[type='" in loc
    ):
        return _P_ATTR
    if loc.startswith("//") or loc.startswith("(//"):
        return _P_XPATH
    return _P_CSS  # generic CSS — tag, class combos, etc.
