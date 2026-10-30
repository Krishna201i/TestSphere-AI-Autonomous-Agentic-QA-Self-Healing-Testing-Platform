"""
TestSphere-AI — Why a test failed, in words a person acts on.

The failure analyzer (``agents/analyzer``) classifies every failure and
explains it; until now that only steered healing.  ``diagnosis_of`` turns its
analysis into what the run page and reports show: the kind of failure, the
analyzer's explanation, expected against actual, its confidence, and a next
step.  The next step is fixed per kind of failure, so the advice is always
sensible even when the explanation came from a small model.
"""

from __future__ import annotations

from typing import Any

LABELS = {
    "SELECTOR_CHANGED": "Element changed",
    "ELEMENT_NOT_FOUND": "Element not found",
    "ELEMENT_NOT_INTERACTABLE": "Element not usable",
    "TIMEOUT": "Timed out",
    "ASSERTION_FAILURE": "Check did not hold",
    "NAVIGATION_FAILURE": "Navigation failed",
    "NETWORK_ERROR": "Network error",
    "APPLICATION_ERROR": "Application error",
    "UNKNOWN": "Unclear cause",
}

NEXT_STEPS = {
    "SELECTOR_CHANGED": "The element's locator no longer matches. If the page changed on purpose, update the test or "
                        "let healing learn the new locator; if not, the element may have gone: check the screenshot.",
    "ELEMENT_NOT_FOUND": "The element is not on the page. Check the screenshot: a missing element is an app bug, a "
                         "renamed one means the test needs its new locator.",
    "ELEMENT_NOT_INTERACTABLE": "The element is there but covered, hidden or disabled, for example behind a menu, a "
                                "dialog or a cookie banner. Open what reveals it first.",
    "TIMEOUT": "The page or element took too long. Check the network errors for a slow or failing request, or raise "
               "the step's timeout if the app is slow by design.",
    "ASSERTION_FAILURE": "The page did not show what the check expected. Compare expected and actual: wrong content "
                         "is an app bug; an outdated wording, path or title means the check needs updating.",
    "NAVIGATION_FAILURE": "The page did not load or ended up elsewhere. Check the URL, redirects and whether it needs "
                          "a signed-in session.",
    "NETWORK_ERROR": "A request failed. The network errors show its URL and status; a 5xx is a server problem.",
    "APPLICATION_ERROR": "The application reported an error (console or server). This is most likely a bug in the app.",
    "UNKNOWN": "No clear cause. Open the screenshot and the trace to see what the page did at that step.",
}


def _value(field: Any) -> str:
    return str(getattr(field, "value", field) or "")


def diagnosis_of(analysis: Any) -> dict[str, Any] | None:
    """The diagnosis to store with a failed execution (*analysis* is a ``FailureAnalysis``)."""
    if analysis is None:
        return None
    kind = _value(analysis.failure_type) or "UNKNOWN"
    kind = kind if kind in LABELS else "UNKNOWN"
    diagnosis = {
        "kind": kind,
        "label": LABELS[kind],
        "explanation": (analysis.root_cause or "").strip()[:600],
        "next_step": NEXT_STEPS[kind],
        "confidence": _value(analysis.confidence).lower() or None,
        "failed_step": analysis.failed_step,
    }
    # Expected and actual: the analysis's own fields, else what its evidence recorded
    found = {key: getattr(analysis, f"{key}_state", None) for key in ("expected", "actual")}
    for item in getattr(analysis, "evidence", None) or []:
        details = getattr(item, "details", None) or {}
        for key in ("expected", "actual"):
            found[key] = found[key] or details.get(key)
    for key, value in found.items():
        if value:
            diagnosis[key] = str(value)[:300]
    return diagnosis
