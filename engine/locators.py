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

from engine.schemas import ElementFingerprint

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
        candidates.append((_P_TESTID, f'[data-testid="{dt}"]'))

    # ---- 1: role + accessible name (ARIA-safe) ----------------------------
    if fp.role and fp.aria_label:
        candidates.append((_P_ROLE, f'[role="{fp.role}"][aria-label="{fp.aria_label}"]'))
    elif fp.role and fp.text:
        txt = fp.text[:80].replace('"', '\\"')
        candidates.append((_P_ROLE, f'[role="{fp.role}"]:has-text("{txt}")'))

    # ---- 2: id ------------------------------------------------------------
    if fp.id:
        candidates.append((_P_ID, f"#{fp.id}"))

    # ---- 3: aria-label standalone (even without role) ---------------------
    if fp.aria_label:
        candidates.append((_P_ARIA, f'[aria-label="{fp.aria_label}"]'))

    # ---- 4: name / placeholder / visible text -----------------------------
    if fp.name:
        candidates.append((_P_ATTR, f'{tag}[name="{fp.name}"]'))

    if fp.placeholder:
        candidates.append((_P_ATTR, f'[placeholder="{fp.placeholder}"]'))

    if fp.text:
        txt = fp.text[:80].replace('"', '\\"')
        candidates.append((_P_ATTR, f'{tag}:has-text("{txt}")'))

    # type attribute (button[type="submit"], input[type="email"], …)
    type_attr = fp.attributes.get("type")
    if type_attr:
        candidates.append((_P_ATTR, f"{tag}[type='{type_attr}']"))

    # ---- 5: CSS (classes, generic tag) ------------------------------------
    if fp.classes:
        cls_str = "".join(f".{c}" for c in fp.classes if c)
        if cls_str:
            candidates.append((_P_CSS, f"{tag}{cls_str}"))

    # ---- 6: XPath (last resort) -------------------------------------------
    if fp.id:
        candidates.append((_P_XPATH, f'//{tag}[@id="{fp.id}"]'))
    elif fp.text:
        txt = fp.text[:80].replace('"', '\\"')
        candidates.append((_P_XPATH, f'//{tag}[contains(normalize-space(),"{txt}")]'))
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
