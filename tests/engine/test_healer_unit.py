"""
tests/engine/test_healer_unit.py
=================================
Unit tests for engine/healer.py — no browser required.

Covers:
- _score_attribute: exact / partial / absent fields
- _score_text: both present, both absent, one absent
- _score_position: same box, far away, no reference box
- _score_structure: matching/different parent chains, sibling index delta
- _weighted: arithmetic correctness
- Threshold behaviour via HealingReport inspection
"""

from __future__ import annotations

import pytest

from engine.healer import (
    _candidate_locator,
    _score_attribute,
    _score_position,
    _score_structure,
    _score_text,
    _weighted,
)
from engine.schemas import BoundingBox, ElementFingerprint, HealingSignals


# ---------------------------------------------------------------------------
# Helpers: fingerprint & candidate factories
# ---------------------------------------------------------------------------


def make_fp(**kwargs) -> ElementFingerprint:
    """Construct an ElementFingerprint with sane defaults."""
    defaults: dict = dict(
        tag="button",
        id=None,
        classes=[],
        text=None,
        role=None,
        aria_label=None,
        name=None,
        placeholder=None,
        attributes={},
        parent_chain=[],
        sibling_index=None,
        bounding_box=None,
    )
    defaults.update(kwargs)
    return ElementFingerprint(**defaults)


def make_cand(**kwargs) -> dict:
    """Construct a candidate info dict with sane defaults."""
    defaults: dict = dict(
        tag="button",
        id=None,
        classes=[],
        text=None,
        role=None,
        aria_label=None,
        name=None,
        placeholder=None,
        attributes={},
        parent_chain=[],
        sibling_index=None,
        rect={"x": 0, "y": 0, "width": 100, "height": 40},
    )
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# _score_attribute
# ---------------------------------------------------------------------------


def test_attribute_perfect_match() -> None:
    fp = make_fp(tag="button", id="btn", classes=["submit"], aria_label="OK")
    cand = make_cand(tag="button", id="btn", classes=["submit"], aria_label="OK")
    score = _score_attribute(fp, cand)
    assert score == pytest.approx(1.0, abs=0.01)


def test_attribute_id_mismatch_lowers_score() -> None:
    fp = make_fp(tag="button", id="btn-a")
    cand = make_cand(tag="button", id="btn-b")
    score = _score_attribute(fp, cand)
    assert score < 1.0


def test_attribute_tag_mismatch_lowers_score() -> None:
    fp = make_fp(tag="button")
    cand = make_cand(tag="a")
    score = _score_attribute(fp, cand)
    assert score < 1.0


def test_attribute_data_testid_exact_match() -> None:
    fp = make_fp(attributes={"data-testid": "submit-btn"})
    cand = make_cand(attributes={"data-testid": "submit-btn"})
    score = _score_attribute(fp, cand)
    assert score == pytest.approx(1.0, abs=0.01)


def test_attribute_data_testid_mismatch() -> None:
    fp = make_fp(attributes={"data-testid": "submit-btn"})
    cand = make_cand(attributes={"data-testid": "cancel-btn"})
    score = _score_attribute(fp, cand)
    assert score < 0.8


def test_attribute_classes_partial_overlap() -> None:
    fp = make_fp(classes=["btn", "primary", "large"])
    cand = make_cand(classes=["btn", "secondary"])
    score = _score_attribute(fp, cand)
    # Jaccard: |{btn}| / |{btn, primary, large, secondary}| = 1/4 = 0.25
    # Combined with other signals, should be between 0 and 1
    assert 0.0 < score < 1.0


def test_attribute_classes_no_overlap() -> None:
    fp = make_fp(classes=["btn", "primary"])
    cand = make_cand(classes=["nav", "item"])
    score = _score_attribute(fp, cand)
    # Classes part → 0, but tag still matches → score is at most 0.5
    assert score <= 0.5


def test_attribute_name_exact_match() -> None:
    fp = make_fp(tag="input", name="email")
    cand = make_cand(tag="input", name="email")
    score = _score_attribute(fp, cand)
    assert score == pytest.approx(1.0, abs=0.01)


def test_attribute_placeholder_match() -> None:
    fp = make_fp(tag="input", placeholder="Enter email")
    cand = make_cand(tag="input", placeholder="Enter email")
    score = _score_attribute(fp, cand)
    assert score == pytest.approx(1.0, abs=0.01)


def test_attribute_minimal_fingerprint_returns_float() -> None:
    """Empty fingerprint should not crash; returns a float in [0,1]."""
    fp = make_fp()
    cand = make_cand()
    score = _score_attribute(fp, cand)
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# _score_text
# ---------------------------------------------------------------------------


def test_text_exact_match() -> None:
    fp = make_fp(text="Log in")
    cand = make_cand(text="Log in")
    assert _score_text(fp, cand) == pytest.approx(1.0)


def test_text_both_none() -> None:
    """Both absent → neutral 1.0."""
    fp = make_fp(text=None)
    cand = make_cand(text=None)
    assert _score_text(fp, cand) == pytest.approx(1.0)


def test_text_one_absent() -> None:
    """One has text, the other doesn't → hard mismatch → 0.0."""
    fp = make_fp(text="Click me")
    cand = make_cand(text=None)
    assert _score_text(fp, cand) == pytest.approx(0.0)


def test_text_similar_strings() -> None:
    fp = make_fp(text="Submit form")
    cand = make_cand(text="Submit")
    score = _score_text(fp, cand)
    assert 0.0 < score < 1.0


def test_text_completely_different() -> None:
    fp = make_fp(text="Login")
    cand = make_cand(text="XYZ9999")
    score = _score_text(fp, cand)
    assert score < 0.5


def test_text_empty_string_treated_as_absent() -> None:
    fp = make_fp(text="")
    cand = make_cand(text="")
    assert _score_text(fp, cand) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _score_position
# ---------------------------------------------------------------------------


def test_position_identical_box() -> None:
    bb = BoundingBox(x=100, y=200, width=80, height=36)
    fp = make_fp(bounding_box=bb)
    cand = make_cand(rect={"x": 100, "y": 200, "width": 80, "height": 36})
    score = _score_position(fp, cand)
    assert score == pytest.approx(1.0, abs=0.01)


def test_position_no_reference_box() -> None:
    """No bounding_box in fingerprint → neutral 0.5."""
    fp = make_fp(bounding_box=None)
    cand = make_cand(rect={"x": 100, "y": 200, "width": 80, "height": 36})
    assert _score_position(fp, cand) == pytest.approx(0.5)


def test_position_far_away_element() -> None:
    bb = BoundingBox(x=0, y=0, width=80, height=36)
    fp = make_fp(bounding_box=bb)
    nearby = make_cand(rect={"x": 0, "y": 0, "width": 80, "height": 36})
    far = make_cand(rect={"x": 1200, "y": 700, "width": 80, "height": 36})
    # Far element must score strictly lower than the same-position element
    assert _score_position(fp, far) < _score_position(fp, nearby)


def test_position_zero_width_candidate() -> None:
    """Candidate not rendered (width=0) → 0.0."""
    bb = BoundingBox(x=100, y=100, width=80, height=36)
    fp = make_fp(bounding_box=bb)
    cand = make_cand(rect={"x": 100, "y": 100, "width": 0, "height": 0})
    assert _score_position(fp, cand) == pytest.approx(0.0)


def test_position_size_mismatch_lowers_score() -> None:
    bb = BoundingBox(x=100, y=100, width=80, height=36)
    fp = make_fp(bounding_box=bb)
    # Same position, very different size
    cand = make_cand(rect={"x": 100, "y": 100, "width": 800, "height": 400})
    score = _score_position(fp, cand)
    assert score < 0.8


# ---------------------------------------------------------------------------
# _score_structure
# ---------------------------------------------------------------------------


def test_structure_identical_chain() -> None:
    chain = ["form#login-form", "div.card"]
    fp = make_fp(parent_chain=chain, sibling_index=0)
    cand = make_cand(parent_chain=chain, sibling_index=0)
    score = _score_structure(fp, cand)
    assert score == pytest.approx(1.0, abs=0.05)


def test_structure_different_chain() -> None:
    fp = make_fp(parent_chain=["form#login-form", "div.card"], sibling_index=0)
    cand = make_cand(parent_chain=["nav#main-nav", "ul.menu"], sibling_index=2)
    score = _score_structure(fp, cand)
    assert score < 0.5


def test_structure_sibling_same_index() -> None:
    fp = make_fp(parent_chain=[], sibling_index=1)
    cand = make_cand(parent_chain=[], sibling_index=1)
    score = _score_structure(fp, cand)
    assert score == pytest.approx(1.0, abs=0.01)


def test_structure_sibling_far_index() -> None:
    fp = make_fp(parent_chain=[], sibling_index=0)
    cand = make_cand(parent_chain=[], sibling_index=10)
    score = _score_structure(fp, cand)
    assert score == pytest.approx(0.0, abs=0.01)


def test_structure_both_sibling_none() -> None:
    fp = make_fp(parent_chain=[], sibling_index=None)
    cand = make_cand(parent_chain=[], sibling_index=None)
    score = _score_structure(fp, cand)
    assert score == pytest.approx(1.0, abs=0.01)


def test_structure_empty_both() -> None:
    fp = make_fp(parent_chain=[], sibling_index=None)
    cand = make_cand(parent_chain=[], sibling_index=None)
    score = _score_structure(fp, cand)
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# _weighted composite
# ---------------------------------------------------------------------------


def test_weighted_all_ones() -> None:
    s = HealingSignals(attribute=1.0, text=1.0, position=1.0, structure=1.0)
    assert _weighted(s) == pytest.approx(1.0)


def test_weighted_all_zeros() -> None:
    s = HealingSignals(attribute=0.0, text=0.0, position=0.0, structure=0.0)
    assert _weighted(s) == pytest.approx(0.0)


def test_weighted_mixed() -> None:
    # 0.40*1.0 + 0.30*0.0 + 0.15*1.0 + 0.15*0.0 = 0.55
    s = HealingSignals(attribute=1.0, text=0.0, position=1.0, structure=0.0)
    assert _weighted(s) == pytest.approx(0.55, abs=0.001)


def test_weighted_attribute_dominates() -> None:
    """Attribute weight (0.40) > text weight (0.30) > position=structure (0.15)."""
    s_attr = HealingSignals(attribute=1.0, text=0.0, position=0.0, structure=0.0)
    s_text = HealingSignals(attribute=0.0, text=1.0, position=0.0, structure=0.0)
    assert _weighted(s_attr) > _weighted(s_text)


def test_weighted_clamped_above_one() -> None:
    """Result must always be in [0, 1]."""
    s = HealingSignals(attribute=1.0, text=1.0, position=1.0, structure=1.0)
    assert _weighted(s) <= 1.0


# ---------------------------------------------------------------------------
# _candidate_locator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "info, expected",
    [
        ({"tag": "button", "id": "btn"}, "#btn"),
        ({"tag": "input", "id": None, "attributes": {"data-testid": "x"}}, '[data-testid="x"]'),
        ({"tag": "button", "id": None, "aria_label": "Close"}, '[aria-label="Close"]'),
        ({"tag": "input", "id": None, "name": "email"}, 'input[name="email"]'),
        ({"tag": "span", "id": None, "text": "Hello"}, '//span[contains(normalize-space(),"Hello")]'),
        ({"tag": "div", "id": None, "classes": ["card"]}, "div.card"),
        ({"tag": "section", "id": None}, None),
    ],
)
def test_candidate_locator_priority(info: dict, expected: str | None) -> None:
    full = make_cand(**info)
    assert _candidate_locator(full) == expected


# ---------------------------------------------------------------------------
# Threshold semantics (pure data, no browser)
# ---------------------------------------------------------------------------


def test_threshold_above_accepts() -> None:
    """Simulate: best score 0.9 >= threshold 0.75 → report should select."""
    from engine.schemas import HealingCandidate, HealingReport

    best = HealingCandidate(
        locator="#healed",
        score=0.9,
        signals=HealingSignals(attribute=0.9, text=0.9, position=0.9, structure=0.9),
    )
    report = HealingReport(
        original_locator="#broken",
        candidates=[best],
        selected_locator=best.locator if best.score >= 0.75 else None,
        confidence=best.score,
        strategy_used="fingerprint",
    )
    assert report.selected_locator == "#healed"
    assert report.confidence == pytest.approx(0.9)


def test_threshold_below_defers() -> None:
    """Simulate: best score 0.4 < threshold 0.75 → selected_locator is None."""
    from engine.schemas import HealingCandidate, HealingReport

    best = HealingCandidate(
        locator="#maybe",
        score=0.4,
        signals=HealingSignals(attribute=0.4, text=0.4, position=0.4, structure=0.4),
    )
    report = HealingReport(
        original_locator="#broken",
        candidates=[best],
        selected_locator=best.locator if best.score >= 0.75 else None,
        confidence=best.score,
        strategy_used="fingerprint",
    )
    assert report.selected_locator is None
    assert report.confidence == pytest.approx(0.4)
