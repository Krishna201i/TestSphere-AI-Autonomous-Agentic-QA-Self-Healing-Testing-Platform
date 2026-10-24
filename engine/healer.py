"""
engine/healer.py
================
Locator self-healing for the TestSphere-AI engine.

Public API
----------
    async def attempt_healing(page, step, config, exc) -> HealingReport | None

Called by ``engine/runner.py`` when a step's primary locator fails.  Two
stages, cheapest first:

1. **Fallbacks** — try ``Target.fallback_locators`` in stored (stability-ranked)
   order.  The first one that resolves to exactly one visible element and
   scores at or above ``EngineConfig.heal_threshold`` is selected.
2. **Fingerprint scan** — if no fallback qualifies and the target has a stored
   ``ElementFingerprint``, harvest live-DOM candidates via
   ``detector.extract_candidates`` and score each one against it.  The best is
   selected only if it clears the threshold *and* beats the runner-up by
   ``AMBIGUITY_MARGIN`` (two near-identical matches = refuse, don't guess).

Every candidate is scored on the four ``HealingSignals``:

    attribute  (0.40)  id / name / placeholder / aria / role / testid / type / classes
    text       (0.20)  visible text similarity (rapidfuzz)
    position   (0.20)  bounding-box centre distance
    structure  (0.20)  parent chain + sibling index

A tag mismatch scores 0 regardless of the other signals — healing a click from
a removed ``<button>`` onto some ``<input>`` is a false heal, never a fix.

A ``HealingReport`` is returned even when nothing is selected, so the agent
layer and dashboard can see what was considered.  ``None`` means healing was
not applicable (step has no target).
"""

from __future__ import annotations

import logging
import re

from playwright.async_api import Page
from rapidfuzz import fuzz

from .detector import build_fingerprint, extract_candidates
from .schemas import (
    ElementFingerprint,
    EngineConfig,
    HealingCandidate,
    HealingReport,
    HealingSignals,
    Step,
)

log = logging.getLogger(__name__)

# Signal weights (sum to 1.0)
W_ATTRIBUTE = 0.40
W_TEXT = 0.20
W_POSITION = 0.20
W_STRUCTURE = 0.20

# Confidence given to a hand-authored fallback when no fingerprint was ever
# captured (e.g. first run of a plan).  Uniqueness + visibility is all we can
# check, so it sits just above the default 0.75 threshold.
FALLBACK_WITHOUT_FINGERPRINT = 0.80

# Fingerprint scan: best candidate must beat the runner-up by this much
AMBIGUITY_MARGIN = 0.05

# Centre-to-centre distance (px) at which the position signal reaches 0
POSITION_FALLOFF_PX = 300.0

# Stable attributes compared for the attribute signal (fingerprint.attributes keys)
_STABLE_ATTRS = ("data-testid", "data-test-id", "type", "autocomplete", "href", "for")

# Identity rules (see score_fingerprint):
# - an unchanged id on the same kind of element is strong evidence even when the
#   element was moved or wrapped: its score is raised to ID_ANCHOR_SCORE;
# - when the stored element had identifying features (id, name, placeholder,
#   aria-label, text, href) and the candidate shares none of them, it is a
#   look-alike, not the same element: its score is capped at NO_IDENTITY_CAP.
ID_ANCHOR_SCORE = 0.85
NO_IDENTITY_CAP = 0.6
TEXT_SAME = 0.8  # fuzzy text ratio that counts as "the same text"

_LOCATOR_ATTR_RE = re.compile(r"\[\s*([\w:-]+)\s*[~|^$*]?=")
_LOCATOR_ID_RE = re.compile(r"#([\w-]+)")
_FIELD_OF_ATTR = {"id": "id", "name": "name", "placeholder": "placeholder", "aria-label": "aria_label", "role": "role"}


def broken_attributes(primary_locator: str) -> frozenset[str]:
    """Attributes the (failed) primary locator matched on.  They have changed by
    definition, so they are not evidence for or against any candidate."""
    attrs = set(_LOCATOR_ATTR_RE.findall(primary_locator or ""))
    if _LOCATOR_ID_RE.search(primary_locator or ""):
        attrs.add("id")
    return frozenset(attrs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def attempt_healing(
    page: Page,
    step: Step,
    config: EngineConfig,
    exc: Exception,  # noqa: ARG001 (kept for hook signature / future error-aware healing)
) -> HealingReport | None:
    """
    Try to find a replacement locator for ``step.target``.

    Returns
    -------
    HealingReport | None
        ``None`` if the step has no target.  Otherwise a report whose
        ``selected_locator`` is set only when a candidate was accepted.
    """
    target = step.target
    if target is None:
        return None

    stored = target.fingerprint
    ignore = broken_attributes(target.primary_locator)
    threshold = config.heal_threshold
    tried = {target.primary_locator}
    candidates: list[HealingCandidate] = []

    # ── Stage 1: stored fallbacks ────────────────────────────────────────
    for index, locator in enumerate(target.fallback_locators):
        if locator in tried:
            continue
        tried.add(locator)

        live = await _resolve_unique(page, locator)
        if live is None:
            continue

        candidate = _candidate(locator, stored, live, ignore)
        candidates.append(candidate)
        if candidate.score >= threshold:
            log.info(
                "Healed %r -> %r via fallback[%d] (score=%.2f)",
                target.primary_locator, locator, index, candidate.score,
            )
            return _report(target.primary_locator, candidates, candidate, f"fallback[{index}]")

    # ── Stage 2: live-DOM fingerprint scan ───────────────────────────────
    if stored is not None:
        for locator in await extract_candidates(page, stored, config.max_candidates):
            if locator in tried:
                continue
            tried.add(locator)

            live = await _resolve_unique(page, locator)
            if live is not None:
                candidates.append(_candidate(locator, stored, live, ignore))

        ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
        if ranked and ranked[0].score >= threshold:
            best = ranked[0]
            runner_up = ranked[1].score if len(ranked) > 1 else 0.0
            if best.score - runner_up >= AMBIGUITY_MARGIN:
                log.info(
                    "Healed %r -> %r via fingerprint (score=%.2f, runner-up=%.2f)",
                    target.primary_locator, best.locator, best.score, runner_up,
                )
                return _report(target.primary_locator, candidates, best, "fingerprint")
            log.info(
                "Refusing ambiguous heal for %r: %r=%.2f vs runner-up %.2f",
                target.primary_locator, best.locator, best.score, runner_up,
            )

    log.info(
        "No safe heal for %r (%d candidates evaluated, threshold=%.2f)",
        target.primary_locator, len(candidates), threshold,
    )
    return _report(target.primary_locator, candidates, None, "none")


def score_fingerprint(
    stored: ElementFingerprint,
    live: ElementFingerprint,
    ignore: frozenset[str] = frozenset(),
) -> tuple[float, HealingSignals]:
    """
    Compare a live element against the stored fingerprint.

    Pure function (no browser) so it can be unit-tested directly.

    Returns
    -------
    tuple[float, HealingSignals]
        Weighted composite score in [0, 1] and the per-signal breakdown.
    """
    signals = HealingSignals(
        attribute=_attribute_signal(stored, live, ignore),
        text=_text_signal(stored, live),
        position=_position_signal(stored, live),
        structure=_structure_signal(stored, live),
    )

    if stored.tag and live.tag and stored.tag != live.tag:
        return 0.0, signals

    score = (
        W_ATTRIBUTE * signals.attribute
        + W_TEXT * signals.text
        + W_POSITION * signals.position
        + W_STRUCTURE * signals.structure
    )
    identity = _identity_matches(stored, live, ignore)
    if identity is False:
        score = min(score, NO_IDENTITY_CAP)
    elif "id" not in ignore and stored.id and live.id == stored.id:
        score = max(score, ID_ANCHOR_SCORE)
    return round(min(max(score, 0.0), 1.0), 4), signals


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------


async def _resolve_unique(page: Page, locator: str) -> ElementFingerprint | None:
    """Fingerprint *locator*'s element if it matches exactly one visible element."""
    try:
        matches = page.locator(locator)
        if await matches.count() != 1 or not await matches.first.is_visible():
            return None
    except Exception as exc:  # noqa: BLE001 - invalid selector syntax, detached frame, …
        log.debug("Candidate %r not resolvable: %s", locator, exc)
        return None
    return await build_fingerprint(page, locator)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _candidate(
    locator: str,
    stored: ElementFingerprint | None,
    live: ElementFingerprint,
    ignore: frozenset[str] = frozenset(),
) -> HealingCandidate:
    if stored is None:
        return HealingCandidate(
            locator=locator, score=FALLBACK_WITHOUT_FINGERPRINT, signals=HealingSignals()
        )
    score, signals = score_fingerprint(stored, live, ignore)
    return HealingCandidate(locator=locator, score=score, signals=signals)


def _report(
    original: str,
    candidates: list[HealingCandidate],
    selected: HealingCandidate | None,
    strategy: str,
) -> HealingReport:
    return HealingReport(
        original_locator=original,
        candidates=sorted(candidates, key=lambda c: c.score, reverse=True),
        selected_locator=selected.locator if selected else None,
        confidence=selected.score if selected else 0.0,
        strategy_used=strategy,
    )


def _identity_matches(stored: ElementFingerprint, live: ElementFingerprint,
                      ignore: frozenset[str]) -> bool | None:
    """Whether the candidate shares any identifying feature with the stored
    element (None when the stored element had none to compare)."""
    checks: list[bool] = []
    for attr, field in _FIELD_OF_ATTR.items():
        expected = getattr(stored, field)
        if attr != "role" and attr not in ignore and expected:
            checks.append(getattr(live, field) == expected)
    if stored.text:
        checks.append(bool(live.text) and fuzz.ratio(stored.text, live.text) / 100.0 >= TEXT_SAME)
    if stored.attributes.get("href") and "href" not in ignore:
        checks.append(live.attributes.get("href") == stored.attributes["href"])
    return any(checks) if checks else None


def _attribute_signal(stored: ElementFingerprint, live: ElementFingerprint,
                      ignore: frozenset[str] = frozenset()) -> float:
    """Fraction of the stored element's identifying attributes the live one shares."""
    checks: list[float] = []

    for attr, field in _FIELD_OF_ATTR.items():
        expected = getattr(stored, field)
        if expected and attr not in ignore:
            checks.append(1.0 if getattr(live, field) == expected else 0.0)

    for key in _STABLE_ATTRS:
        if key in ignore:
            continue
        expected = stored.attributes.get(key)
        if expected:
            checks.append(1.0 if live.attributes.get(key) == expected else 0.0)

    if stored.classes:
        a, b = set(stored.classes), set(live.classes)
        checks.append(len(a & b) / len(a | b))

    return sum(checks) / len(checks) if checks else 0.5


def _text_signal(stored: ElementFingerprint, live: ElementFingerprint) -> float:
    if not stored.text and not live.text:
        return 1.0  # e.g. inputs — no text on either side is a match
    if not stored.text or not live.text:
        return 0.0
    return fuzz.ratio(stored.text, live.text) / 100.0


def _position_signal(stored: ElementFingerprint, live: ElementFingerprint) -> float:
    a, b = stored.bounding_box, live.bounding_box
    if a is None or b is None:
        return 0.5  # unknown — neither reward nor punish
    dx = (a.x + a.width / 2) - (b.x + b.width / 2)
    dy = (a.y + a.height / 2) - (b.y + b.height / 2)
    distance = (dx * dx + dy * dy) ** 0.5
    return max(0.0, 1.0 - distance / POSITION_FALLOFF_PX)


def _structure_signal(stored: ElementFingerprint, live: ElementFingerprint) -> float:
    parts: list[float] = []

    if stored.parent_chain or live.parent_chain:
        depth = max(len(stored.parent_chain), len(live.parent_chain))
        same = sum(1 for x, y in zip(stored.parent_chain, live.parent_chain, strict=False) if x == y)  # chains may differ in depth
        parts.append(same / depth)

    if stored.sibling_index is not None:
        parts.append(1.0 if stored.sibling_index == live.sibling_index else 0.0)

    return sum(parts) / len(parts) if parts else 0.5
