"""
engine/healer.py
================
Self-healing locator recovery for the TestSphere-AI engine.

Public API
----------
    async def attempt_healing(
        page: Page,
        step: Step,
        config: EngineConfig,
        exc: Exception,
    ) -> HealingReport | None

Algorithm
---------
(a) **Fallback sweep** — try each ``Target.fallback_locators`` in rank order.
    First visible match → instant HealingReport(strategy="fallback[i]",
    confidence=1.0, selected_locator=<fallback>).

(b) **Fingerprint scoring** — if all fallbacks fail and a fingerprint exists,
    query the live DOM for candidate elements, score each against the stored
    fingerprint using four weighted signals, and accept the best candidate
    automatically iff ``score >= config.heal_threshold``.

(c) **Deferred** — if no candidate clears the threshold (or no fingerprint),
    return a HealingReport with ``selected_locator=None`` so that Member 1's
    agent can decide.  The ranked candidates are still included.

Never returns ``None`` when a Target exists; returns ``None`` only for
actions that have no target (goto, wait_for).

Signal weights (empirical; ponytail: expose in EngineConfig if per-project
tuning is needed):
    attribute  0.40 — id, classes, aria-label, data-testid, name, placeholder
    text       0.30 — rapidfuzz ratio on visible inner-text
    position   0.15 — bounding-box proximity / size similarity
    structure  0.15 — parent-chain + sibling-index similarity
"""

from __future__ import annotations

import logging
import math
from typing import Any

from rapidfuzz import fuzz
from playwright.async_api import Page

from .schemas import (
    EngineConfig,
    ElementFingerprint,
    HealingCandidate,
    HealingReport,
    HealingSignals,
    Step,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weight constants
# ponytail: empirical; upgrade path = add to EngineConfig and calibrate per-project
# ---------------------------------------------------------------------------

_W_ATTRIBUTE = 0.40
_W_TEXT = 0.30
_W_POSITION = 0.15
_W_STRUCTURE = 0.15

# Short timeout used when probing whether a fallback locator is visible
_PROBE_TIMEOUT_MS = 2_000

# CSS selectors that capture the vast majority of interactive elements
_CANDIDATE_SELECTORS = [
    "button", "input", "a", "select", "textarea",
    "[role]", "[data-testid]", "[aria-label]",
]

# JS that extracts full element descriptors (tag + attributes + geometry)
# from the live DOM in one round-trip.
_EXTRACT_JS = """\
([selectors, tag, maxN]) => {
    const seen = new Set();
    const raw  = [];
    const SKIP = new Set(['id','class','role','aria-label','name','placeholder']);
    const query = [...new Set([tag, ...selectors])];

    for (const sel of query) {
        for (const el of document.querySelectorAll(sel)) {
            if (!seen.has(el) && raw.length < maxN * 3) {
                seen.add(el);

                // parent chain: nearest first, up to 5 levels
                const chain = [];
                let p = el.parentElement;
                while (p && p !== document.body && chain.length < 5) {
                    const id  = p.id ? '#' + p.id : '';
                    const cls = p.classList.length ? '.' + [...p.classList].join('.') : '';
                    chain.push(p.tagName.toLowerCase() + id + cls);
                    p = p.parentElement;
                }

                // sibling index among same-tag siblings
                let sibIdx = null;
                if (el.parentElement) {
                    const sibs = [...el.parentElement.children]
                        .filter(c => c.tagName === el.tagName);
                    sibIdx = sibs.indexOf(el);
                }

                // extra attributes
                const attrs = {};
                for (const a of el.attributes) {
                    if (!SKIP.has(a.name)) attrs[a.name] = a.value;
                }

                // bounding rect for position scoring
                const r = el.getBoundingClientRect();

                raw.push({
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
                    rect:         { x: r.x, y: r.y, width: r.width, height: r.height },
                });
            }
        }
    }
    return raw;
}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def attempt_healing(
    page: Page,
    step: Step,
    config: EngineConfig,
    exc: Exception,
) -> HealingReport | None:
    """
    Attempt to recover a failed locator and return a ``HealingReport``.

    Returns ``None`` when the step has no ``Target`` (healing not applicable).
    Always returns a ``HealingReport`` when a Target is present — even on total
    failure — so Member 1's agent and Member 3's dashboard see the candidates.

    Parameters
    ----------
    page:   Live Playwright page (still on the same URL where the step failed).
    step:   The failing step (provides Target, action, timeout).
    config: Engine config (heal_threshold, max_candidates).
    exc:    The exception that triggered healing (used only for logging).
    """
    if step.target is None:
        return None

    original = step.target.primary_locator
    log.info(
        "Healing triggered for %r (%s: %s)",
        original, type(exc).__name__, str(exc)[:120],
    )

    # (a) Fallback sweep
    report = await _try_fallbacks(page, step.target, original)
    if report is not None:
        return report

    # (b) Fingerprint-based scoring
    return await _heal_by_fingerprint(page, step.target, config, original)


# ---------------------------------------------------------------------------
# Phase (a): fallback sweep
# ---------------------------------------------------------------------------


async def _try_fallbacks(
    page: Page,
    target: "Step",  # actually engine.schemas.Target
    original_locator: str,
) -> HealingReport | None:
    """
    Try each stored fallback in rank order.

    Returns a ``HealingReport`` on the first visible hit, or ``None`` if all
    fallbacks fail (so the caller can escalate to fingerprint scoring).
    """
    for i, fallback in enumerate(target.fallback_locators):  # type: ignore[attr-defined]
        if await _locator_visible(page, fallback):
            log.info("Healed via fallback[%d]: %r", i, fallback)
            return HealingReport(
                original_locator=original_locator,
                candidates=[
                    HealingCandidate(
                        locator=fallback,
                        score=1.0,
                        signals=HealingSignals(
                            attribute=1.0, text=1.0, position=1.0, structure=1.0
                        ),
                    )
                ],
                selected_locator=fallback,
                confidence=1.0,
                strategy_used=f"fallback[{i}]",
            )
    return None


# ---------------------------------------------------------------------------
# Phase (b): fingerprint-based scoring
# ---------------------------------------------------------------------------


async def _heal_by_fingerprint(
    page: Page,
    target: Any,  # engine.schemas.Target
    config: EngineConfig,
    original_locator: str,
) -> HealingReport:
    """
    Score live-DOM candidates against ``target.fingerprint``.

    Always returns a ``HealingReport``.  ``selected_locator`` is populated
    only when the best candidate score >= ``config.heal_threshold``.
    """
    fp: ElementFingerprint | None = target.fingerprint  # type: ignore[attr-defined]

    if fp is None:
        log.warning("No fingerprint available for %r — returning empty report", original_locator)
        return HealingReport(
            original_locator=original_locator,
            strategy_used="no_fingerprint",
        )

    raw_candidates = await _extract_candidate_data(page, fp, config.max_candidates)

    scored: list[HealingCandidate] = []
    seen_locators: set[str] = set()

    for info in raw_candidates:
        loc = _candidate_locator(info)
        if not loc or loc == original_locator or loc in seen_locators:
            continue
        seen_locators.add(loc)

        signals = _score_signals(fp, info)
        composite = _weighted(signals)
        scored.append(HealingCandidate(locator=loc, score=composite, signals=signals))

    scored.sort(key=lambda c: c.score, reverse=True)
    scored = scored[: config.max_candidates]

    if scored and scored[0].score >= config.heal_threshold:
        best = scored[0]
        log.info(
            "Fingerprint heal accepted %r (score=%.3f >= threshold=%.3f)",
            best.locator, best.score, config.heal_threshold,
        )
        return HealingReport(
            original_locator=original_locator,
            candidates=scored,
            selected_locator=best.locator,
            confidence=best.score,
            strategy_used="fingerprint",
        )

    top_score = scored[0].score if scored else 0.0
    log.info(
        "Fingerprint heal deferred for %r (best=%.3f < threshold=%.3f)",
        original_locator, top_score, config.heal_threshold,
    )
    return HealingReport(
        original_locator=original_locator,
        candidates=scored,
        selected_locator=None,
        confidence=top_score,
        strategy_used="fingerprint",
    )


# ---------------------------------------------------------------------------
# DOM candidate extraction
# ---------------------------------------------------------------------------


async def _extract_candidate_data(
    page: Page,
    fp: ElementFingerprint,
    max_candidates: int,
) -> list[dict]:
    """Query the live DOM and return raw element descriptor dicts."""
    tag = fp.tag or "button"
    try:
        return await page.evaluate(_EXTRACT_JS, [_CANDIDATE_SELECTORS, tag, max_candidates])
    except Exception as exc:
        log.warning("Candidate extraction JS failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_signals(fp: ElementFingerprint, info: dict) -> HealingSignals:
    """Compute the four similarity signals between *fp* and *info*."""
    return HealingSignals(
        attribute=_score_attribute(fp, info),
        text=_score_text(fp, info),
        position=_score_position(fp, info),
        structure=_score_structure(fp, info),
    )


def _weighted(signals: HealingSignals) -> float:
    """Weighted composite of the four signals, clamped to [0, 1]."""
    raw = (
        signals.attribute * _W_ATTRIBUTE
        + signals.text * _W_TEXT
        + signals.position * _W_POSITION
        + signals.structure * _W_STRUCTURE
    )
    return min(1.0, max(0.0, raw))


def _score_attribute(fp: ElementFingerprint, info: dict) -> float:
    """
    Similarity across id, tag, classes, aria-label, name, placeholder,
    and data-testid.  Jaccard for sets; rapidfuzz ratio for strings.
    """
    scores: list[float] = []

    # tag match (always present; worth checking even if obvious)
    if fp.tag:
        scores.append(1.0 if info.get("tag") == fp.tag else 0.0)

    # id: strong signal — exact match or both absent
    fp_id = fp.id
    cand_id = info.get("id")
    if fp_id is not None or cand_id is not None:
        scores.append(1.0 if fp_id == cand_id else 0.0)

    # data-testid
    fp_dt = fp.attributes.get("data-testid")
    cand_dt = (info.get("attributes") or {}).get("data-testid")
    if fp_dt is not None or cand_dt is not None:
        scores.append(1.0 if fp_dt == cand_dt else 0.0)

    # classes: Jaccard similarity
    fp_cls = set(fp.classes)
    cand_cls = set(info.get("classes") or [])
    if fp_cls or cand_cls:
        union = fp_cls | cand_cls
        inter = fp_cls & cand_cls
        scores.append(len(inter) / len(union) if union else 1.0)

    # aria-label: fuzzy string match
    fp_al = fp.aria_label or ""
    cand_al = info.get("aria_label") or ""
    if fp_al or cand_al:
        if fp_al and cand_al:
            scores.append(fuzz.ratio(fp_al, cand_al) / 100.0)
        else:
            scores.append(0.0)

    # name (form elements)
    fp_nm = fp.name
    cand_nm = info.get("name")
    if fp_nm is not None or cand_nm is not None:
        scores.append(1.0 if fp_nm == cand_nm else 0.0)

    # placeholder
    fp_ph = fp.placeholder
    cand_ph = info.get("placeholder")
    if fp_ph is not None or cand_ph is not None:
        scores.append(1.0 if fp_ph == cand_ph else 0.0)

    return sum(scores) / len(scores) if scores else 0.0


def _score_text(fp: ElementFingerprint, info: dict) -> float:
    """
    rapidfuzz.fuzz.ratio on visible inner-text.

    Both absent → 1.0 (neutral match).
    One absent  → 0.0 (definite mismatch).
    Both present → normalised ratio in [0, 1].
    """
    fp_text = (fp.text or "").strip()
    cand_text = (info.get("text") or "").strip()

    if not fp_text and not cand_text:
        return 1.0  # both empty → neutral
    if not fp_text or not cand_text:
        return 0.0  # one has text, the other doesn't
    return fuzz.ratio(fp_text, cand_text) / 100.0


def _score_position(fp: ElementFingerprint, info: dict) -> float:
    """
    Bounding-box proximity + size similarity.

    Returns 0.5 when no reference bounding box is available in *fp*
    (neutral — we can't penalise or reward).
    """
    bb = fp.bounding_box
    if bb is None:
        return 0.5  # no reference → neutral

    rect = info.get("rect")
    if not rect or rect.get("width", 0) == 0:
        return 0.0  # candidate off-screen or not rendered

    # Centre-point proximity, normalised by viewport diagonal (~1480px for 1280×720)
    fp_cx = bb.x + bb.width / 2
    fp_cy = bb.y + bb.height / 2
    c_cx = rect["x"] + rect["width"] / 2
    c_cy = rect["y"] + rect["height"] / 2
    dist = math.sqrt((fp_cx - c_cx) ** 2 + (fp_cy - c_cy) ** 2)
    ref_diag = math.sqrt(1280**2 + 720**2)
    proximity = max(0.0, 1.0 - dist / ref_diag)

    # Width similarity
    w_ratio = (
        min(bb.width, rect["width"]) / max(bb.width, rect["width"])
        if bb.width > 0 and rect["width"] > 0
        else (1.0 if bb.width == rect["width"] else 0.5)
    )

    # Height similarity
    h_ratio = (
        min(bb.height, rect["height"]) / max(bb.height, rect["height"])
        if bb.height > 0 and rect["height"] > 0
        else (1.0 if bb.height == rect["height"] else 0.5)
    )

    return (proximity + w_ratio + h_ratio) / 3.0


def _score_structure(fp: ElementFingerprint, info: dict) -> float:
    """
    Structural similarity: parent-chain text overlap + sibling-index proximity.
    """
    scores: list[float] = []

    fp_chain = fp.parent_chain
    cand_chain = info.get("parent_chain") or []

    if fp_chain or cand_chain:
        max_len = max(len(fp_chain), len(cand_chain))
        min_len = min(len(fp_chain), len(cand_chain))
        if max_len == 0:
            scores.append(1.0)
        elif min_len == 0:
            scores.append(0.0)
        else:
            # Fuzzy match each ancestor pair (nearest-first), penalise length diff
            pair_scores = [
                fuzz.ratio(a, b) / 100.0
                for a, b in zip(fp_chain[:min_len], cand_chain[:min_len])
            ]
            avg_pair = sum(pair_scores) / min_len
            depth_penalty = min_len / max_len  # penalise different depths
            scores.append(avg_pair * depth_penalty)

    # Sibling index
    fp_sib = fp.sibling_index
    cand_sib = info.get("sibling_index")
    if fp_sib is not None and cand_sib is not None:
        diff = abs(fp_sib - cand_sib)
        scores.append(max(0.0, 1.0 - diff * 0.25))  # 0→1.0, 1→0.75, 4+→0.0
    elif fp_sib is None and cand_sib is None:
        scores.append(1.0)
    else:
        scores.append(0.5)

    return sum(scores) / len(scores) if scores else 0.5


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


async def _locator_visible(page: Page, locator_str: str) -> bool:
    """Return True if *locator_str* matches at least one visible element."""
    try:
        await page.locator(locator_str).first.wait_for(
            state="visible", timeout=_PROBE_TIMEOUT_MS
        )
        return True
    except Exception:
        return False


def _candidate_locator(info: dict) -> str | None:
    """Build the most stable Playwright locator for a candidate descriptor."""
    tag = (info.get("tag") or "element").lower()

    if info.get("id"):
        return f'#{info["id"]}'

    attrs = info.get("attributes") or {}
    if attrs.get("data-testid"):
        return f'[data-testid="{attrs["data-testid"]}"]'

    if info.get("aria_label"):
        al = info["aria_label"].replace('"', '\\"')
        return f'[aria-label="{al}"]'

    if info.get("name"):
        return f'{tag}[name="{info["name"]}"]'

    text = (info.get("text") or "").strip()
    if text:
        escaped = text[:60].replace('"', '\\"')
        return f'//{tag}[contains(normalize-space(),"{escaped}")]'

    classes = info.get("classes") or []
    if classes:
        return f'{tag}.{classes[0]}'

    return None
