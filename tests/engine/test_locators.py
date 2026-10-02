"""
tests/engine/test_locators.py
=============================
Unit tests for engine/locators.py — no browser required.

Covers:
- generate_locators priority ordering (data-testid > role+name > id > …)
- generate_locators output content for various fingerprint shapes
- rank_locators ordering
- Edge cases: empty fingerprint, single-item list, duplicates
"""

from __future__ import annotations

import pytest

from engine.locators import generate_locators, rank_locators, _locator_priority
from engine.schemas import BoundingBox, ElementFingerprint


# ---------------------------------------------------------------------------
# generate_locators — priority ordering
# ---------------------------------------------------------------------------


def test_data_testid_is_first() -> None:
    """data-testid must be the first locator when present."""
    fp = ElementFingerprint(
        tag="button",
        id="btn",
        text="Submit",
        attributes={"data-testid": "submit-btn"},
    )
    locs = generate_locators(fp)
    assert locs[0] == '[data-testid="submit-btn"]'


def test_id_before_xpath_when_no_testid() -> None:
    fp = ElementFingerprint(tag="button", id="my-btn", text="Click me")
    locs = generate_locators(fp)
    assert "#my-btn" in locs
    xpath = next((l for l in locs if l.startswith("//")), None)
    assert xpath is not None
    assert locs.index("#my-btn") < locs.index(xpath)


def test_role_with_aria_label_before_id() -> None:
    """role+aria-label (priority 1) must appear before plain id (priority 2)."""
    fp = ElementFingerprint(
        tag="button",
        id="close-btn",
        role="button",
        aria_label="Close dialog",
    )
    locs = generate_locators(fp)
    role_loc = next(l for l in locs if "role" in l)
    assert '[aria-label="Close dialog"]' in role_loc
    assert locs.index(role_loc) < locs.index("#close-btn")


def test_id_before_aria_standalone() -> None:
    """id (priority 2) must come before standalone aria-label (priority 3)."""
    fp = ElementFingerprint(tag="button", id="btn", aria_label="Submit form")
    locs = generate_locators(fp)
    assert locs.index("#btn") < locs.index('[aria-label="Submit form"]')


def test_text_locator_after_id() -> None:
    fp = ElementFingerprint(tag="a", id="home-link", text="Go home")
    locs = generate_locators(fp)
    text_loc = next(l for l in locs if ":has-text(" in l)
    assert locs.index("#home-link") < locs.index(text_loc)


def test_xpath_is_last() -> None:
    """XPath must always be the last locator."""
    fp = ElementFingerprint(
        tag="div",
        id="my-div",
        classes=["container"],
        text="Hello",
        attributes={"data-testid": "main-container"},
    )
    locs = generate_locators(fp)
    assert locs[-1].startswith("//")


# ---------------------------------------------------------------------------
# generate_locators — content correctness
# ---------------------------------------------------------------------------


def test_data_testid_selector_format() -> None:
    fp = ElementFingerprint(tag="input", attributes={"data-testid": "email-input"})
    locs = generate_locators(fp)
    assert '[data-testid="email-input"]' in locs


def test_id_selector_format() -> None:
    fp = ElementFingerprint(tag="button", id="submit")
    locs = generate_locators(fp)
    assert "#submit" in locs


def test_name_attribute_included() -> None:
    fp = ElementFingerprint(tag="input", name="username")
    locs = generate_locators(fp)
    assert 'input[name="username"]' in locs


def test_placeholder_included() -> None:
    fp = ElementFingerprint(tag="input", placeholder="Enter password")
    locs = generate_locators(fp)
    assert any('[placeholder="Enter password"]' in l for l in locs)


def test_css_classes_included() -> None:
    fp = ElementFingerprint(tag="button", classes=["btn", "primary"])
    locs = generate_locators(fp)
    assert any("btn" in l and "primary" in l for l in locs)


def test_xpath_with_id() -> None:
    fp = ElementFingerprint(tag="div", id="wrapper")
    locs = generate_locators(fp)
    assert '//div[@id="wrapper"]' in locs


def test_xpath_with_text_fallback() -> None:
    fp = ElementFingerprint(tag="span", text="Hello")
    locs = generate_locators(fp)
    xpath = next(l for l in locs if l.startswith("//"))
    assert "Hello" in xpath


def test_xpath_bare_tag_when_no_id_or_text() -> None:
    fp = ElementFingerprint(tag="section")
    locs = generate_locators(fp)
    assert "//section" in locs


def test_no_duplicates() -> None:
    fp = ElementFingerprint(
        tag="button",
        id="btn",
        text="Go",
        classes=["submit"],
        attributes={"data-testid": "go-btn"},
    )
    locs = generate_locators(fp)
    assert len(locs) == len(set(locs))


def test_no_empty_strings() -> None:
    fp = ElementFingerprint(
        tag="button",
        id="",          # empty id should not produce "#"
        classes=[],
        text="",
    )
    locs = generate_locators(fp)
    assert all(loc for loc in locs)  # no empty strings


def test_role_with_text_when_no_aria_label() -> None:
    fp = ElementFingerprint(tag="button", role="button", text="Save")
    locs = generate_locators(fp)
    assert any('[role="button"]:has-text("Save")' in l for l in locs)


def test_type_attribute_included() -> None:
    fp = ElementFingerprint(tag="input", attributes={"type": "submit"})
    locs = generate_locators(fp)
    assert any("[type=" in l for l in locs)


# ---------------------------------------------------------------------------
# rank_locators
# ---------------------------------------------------------------------------


def test_rank_testid_first() -> None:
    locs = ["//div", "#my-id", '[data-testid="x"]', "div.cls"]
    ranked = rank_locators(locs)
    assert ranked[0] == '[data-testid="x"]'


def test_rank_xpath_last() -> None:
    locs = ["//button", "#btn", "button.cls"]
    ranked = rank_locators(locs)
    assert ranked[-1] == "//button"


def test_rank_id_before_css() -> None:
    assert rank_locators(["div.cls", "#my-id"]) == ["#my-id", "div.cls"]


def test_rank_aria_before_text() -> None:
    locs = ['button:has-text("OK")', '[aria-label="OK"]']
    ranked = rank_locators(locs)
    assert ranked[0] == '[aria-label="OK"]'


def test_rank_role_plus_name_before_id() -> None:
    locs = ["#btn", '[role="button"][aria-label="Submit"]']
    ranked = rank_locators(locs)
    assert ranked[0] == '[role="button"][aria-label="Submit"]'


def test_rank_empty_list() -> None:
    assert rank_locators([]) == []


def test_rank_single_item() -> None:
    assert rank_locators(["#x"]) == ["#x"]


def test_rank_is_stable_for_equal_priority() -> None:
    """Equal-priority items must preserve their relative order (stable sort)."""
    locs = ["div.a", "span.b", "p.c"]  # all CSS bucket
    ranked = rank_locators(locs)
    assert ranked == ["div.a", "span.b", "p.c"]


def test_rank_name_attr_before_generic_css() -> None:
    locs = ["div.wrapper", 'input[name="email"]']
    ranked = rank_locators(locs)
    assert ranked[0] == 'input[name="email"]'


# ---------------------------------------------------------------------------
# _locator_priority helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "locator, expected_bucket",
    [
        ('[data-testid="x"]', 0),
        ('[role="button"][aria-label="OK"]', 1),
        ('[role="button"]:has-text("OK")', 1),
        ("#my-id", 2),
        ('[aria-label="Close"]', 3),
        (':has-text("Submit")', 4),
        ('[name="email"]', 4),
        ('[placeholder="Enter"]', 4),
        ("div.container", 5),
        ("button", 5),
        ("//div", 6),
        ("(//button)[1]", 6),
    ],
)
def test_locator_priority_buckets(locator: str, expected_bucket: int) -> None:
    assert _locator_priority(locator) == expected_bucket
