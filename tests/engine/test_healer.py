"""
tests/engine/test_healer.py
===========================
Tests for engine/healer.py.

- ``score_fingerprint`` unit tests — pure Python, no browser.
- Integration tests — the demo app is copied to a temp dir, a baseline run
  captures fingerprints/fallbacks, then ``index.html`` is mutated and the
  plan re-run to check that the runner heals (or correctly refuses).
"""

from __future__ import annotations

import copy
import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from engine.healer import FALLBACK_WITHOUT_FINGERPRINT, score_fingerprint
from engine.runner import run_test
from engine.schemas import (
    ActionType,
    BoundingBox,
    ElementFingerprint,
    RunOptions,
    Step,
    StepStatus,
    Target,
    TestPlan,
    TestStatus,
)

DEMO_DIR = Path(__file__).parent / "demo_app"


# ---------------------------------------------------------------------------
# score_fingerprint — unit tests
# ---------------------------------------------------------------------------


def _button_fp(**overrides) -> ElementFingerprint:
    values = dict(
        tag="button",
        id="login-btn",
        text="Log in",
        attributes={"type": "submit", "data-testid": "login-button"},
        parent_chain=["form#login-form", "div.card"],
        sibling_index=0,
        bounding_box=BoundingBox(x=100, y=300, width=200, height=40),
    )
    values.update(overrides)
    return ElementFingerprint(**values)


def test_identical_element_scores_one() -> None:
    score, signals = score_fingerprint(_button_fp(), _button_fp())
    assert score == pytest.approx(1.0)
    assert signals.attribute == signals.text == signals.position == signals.structure == 1.0


def test_renamed_testid_still_clears_default_threshold() -> None:
    live = _button_fp(attributes={"type": "submit", "data-testid": "submit-btn"})
    score, signals = score_fingerprint(_button_fp(), live)
    assert signals.attribute == pytest.approx(2 / 3)
    assert score >= 0.75


def test_tag_mismatch_scores_zero() -> None:
    live = _button_fp(tag="input")
    score, _ = score_fingerprint(_button_fp(), live)
    assert score == 0.0


def test_text_similarity_is_fuzzy() -> None:
    _, close = score_fingerprint(_button_fp(), _button_fp(text="Log in now"))
    _, far = score_fingerprint(_button_fp(), _button_fp(text="Delete account"))
    assert close.text > 0.7
    assert far.text < 0.4


def test_text_absent_on_both_sides_is_a_match() -> None:
    fp = ElementFingerprint(tag="input", id="username")
    _, signals = score_fingerprint(fp, fp)
    assert signals.text == 1.0


def test_position_falls_off_with_distance() -> None:
    moved = _button_fp(bounding_box=BoundingBox(x=100, y=450, width=200, height=40))
    gone = _button_fp(bounding_box=BoundingBox(x=900, y=900, width=200, height=40))
    _, near = score_fingerprint(_button_fp(), moved)
    _, far = score_fingerprint(_button_fp(), gone)
    assert near.position == pytest.approx(0.5)
    assert far.position == 0.0


def test_missing_bounding_box_is_neutral() -> None:
    _, signals = score_fingerprint(_button_fp(bounding_box=None), _button_fp())
    assert signals.position == 0.5


def test_structure_compares_parent_chain_and_sibling_index() -> None:
    live = _button_fp(parent_chain=["form#other", "div.card"], sibling_index=1)
    _, signals = score_fingerprint(_button_fp(), live)
    assert signals.structure == pytest.approx(0.25)  # (1/2 chain + 0 sibling) / 2


def test_class_overlap_uses_jaccard() -> None:
    stored = ElementFingerprint(tag="div", classes=["a", "b"])
    live = ElementFingerprint(tag="div", classes=["b", "c"])
    _, signals = score_fingerprint(stored, live)
    assert signals.attribute == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# Integration — mutable copy of the demo app
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[misc]
    """Serve a writable copy of demo_app; yields (base_url, site_dir)."""
    site_dir = tmp_path_factory.mktemp("healer_site")
    for f in DEMO_DIR.glob("*.html"):
        shutil.copy(f, site_dir / f.name)

    handler = partial(SimpleHTTPRequestHandler, directory=str(site_dir))
    handler.log_message = lambda *_: None  # type: ignore[method-assign]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", site_dir
    server.shutdown()


@pytest.fixture
def mutate(site):
    """Rewrite index.html via (old, new) replacements; restored after the test."""
    _, site_dir = site
    index = site_dir / "index.html"
    original = (DEMO_DIR / "index.html").read_text(encoding="utf-8")

    def apply(*replacements: tuple[str, str]) -> None:
        html = original
        for old, new in replacements:
            assert old in html, old
            html = html.replace(old, new)
        index.write_text(html, encoding="utf-8")

    index.write_text(original, encoding="utf-8")
    yield apply
    index.write_text(original, encoding="utf-8")


OPTIONS = RunOptions(default_timeout_ms=1_000)


def _login_plan(base: str, button: Target) -> TestPlan:
    return TestPlan(
        test_id="healer-login",
        name="Healer login flow",
        base_url=base,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=f"{base}/index.html"),
            Step(
                step_id="fill-username",
                action=ActionType.FILL,
                target=Target(description="Username", primary_locator="#username"),
                value="admin",
            ),
            Step(
                step_id="fill-password",
                action=ActionType.FILL,
                target=Target(description="Password", primary_locator="#password"),
                value="password",
            ),
            Step(step_id="click-login", action=ActionType.CLICK, target=button),
            Step(
                step_id="assert-welcome",
                action=ActionType.ASSERT_TEXT,
                target=Target(description="Welcome", primary_locator="#welcome-msg"),
                expected="Welcome, admin!",
            ),
        ],
    )


async def _enriched_plan(base: str) -> TestPlan:
    """Run the unmodified app once so the button target gains a fingerprint."""
    plan = _login_plan(
        base,
        Target(description="Login button", primary_locator='[data-testid="login-button"]'),
    )
    result = await run_test(plan, OPTIONS)
    assert result.status == TestStatus.PASSED
    assert plan.steps[3].target.fingerprint is not None
    return plan


def _click(result):
    return next(s for s in result.steps if s.step_id == "click-login")


async def test_heals_renamed_testid_via_fallback(site, mutate) -> None:
    base, _ = site
    plan = await _enriched_plan(base)
    mutate(('data-testid="login-button"', 'data-testid="submit-btn"'))

    result = await run_test(copy.deepcopy(plan), OPTIONS)

    click = _click(result)
    assert click.status == StepStatus.HEALED
    assert click.healing.strategy_used.startswith("fallback[")
    assert click.healing.confidence >= 0.75
    assert result.status == TestStatus.HEALED  # later steps still ran and passed


async def test_heals_via_fingerprint_scan_when_fallbacks_are_dead(site, mutate) -> None:
    base, _ = site
    plan = await _enriched_plan(base)
    plan.steps[3].target.fallback_locators = ["#gone-1", "#gone-2"]
    mutate(('data-testid="login-button"', 'data-testid="submit-btn"'))

    result = await run_test(plan, OPTIONS)

    click = _click(result)
    assert click.status == StepStatus.HEALED
    assert click.healing.strategy_used == "fingerprint"
    assert click.locator_used == click.healing.selected_locator


async def test_hand_written_fallback_heals_without_fingerprint(site, mutate) -> None:
    base, _ = site
    mutate(('data-testid="login-button"', 'data-testid="submit-btn"'))
    button = Target(
        description="Login button",
        primary_locator='[data-testid="login-button"]',
        fallback_locators=["#missing", "#login-btn"],
    )

    result = await run_test(_login_plan(base, button), OPTIONS)

    click = _click(result)
    assert click.status == StepStatus.HEALED
    assert click.healing.selected_locator == "#login-btn"
    assert click.healing.strategy_used == "fallback[1]"
    assert click.healing.confidence == FALLBACK_WITHOUT_FINGERPRINT


async def test_refuses_when_element_removed(site, mutate) -> None:
    base, _ = site
    plan = await _enriched_plan(base)
    mutate((
        '<button id="login-btn" type="submit" data-testid="login-button">\n        Log in\n      </button>',
        "<!-- button removed -->",
    ))

    result = await run_test(plan, OPTIONS)

    click = _click(result)
    assert click.status == StepStatus.FAILED
    assert click.healing is not None
    assert click.healing.selected_locator is None
    assert click.healing.strategy_used == "none"


async def test_refuses_to_heal_onto_different_tag(site, mutate) -> None:
    """Same id/testid but now an <input>: a click target changed kind — refuse."""
    base, _ = site
    plan = await _enriched_plan(base)
    plan.steps[3].target.primary_locator = "#renamed-away"
    mutate((
        '<button id="login-btn" type="submit" data-testid="login-button">\n        Log in\n      </button>',
        '<input id="login-btn" type="submit" data-testid="login-button" value="Log in" />',
    ))

    result = await run_test(plan, OPTIONS)

    click = _click(result)
    assert click.status == StepStatus.FAILED
    assert click.healing.selected_locator is None
    assert click.healing.candidates, "fallbacks resolved but must have been rejected"
    assert all(c.score == 0.0 for c in click.healing.candidates if "login" in c.locator)


async def test_skips_non_unique_candidates(site, mutate) -> None:
    """A fallback matching two elements is never selected."""
    base, _ = site
    mutate(
        ('data-testid="login-button"', 'data-testid="submit-btn"'),
        ("</form>", '<button type="button">Other</button></form>'),
    )
    button = Target(
        description="Login button",
        primary_locator='[data-testid="login-button"]',
        fallback_locators=["form button"],
    )

    result = await run_test(_login_plan(base, button), OPTIONS)

    click = _click(result)
    assert click.status == StepStatus.FAILED
    assert click.healing.candidates == []


# ---------------------------------------------------------------------------
# Identity rules
# ---------------------------------------------------------------------------


def test_the_broken_primary_attribute_is_not_held_against_candidates():
    from engine.healer import broken_attributes

    assert broken_attributes('[data-testid="login-button"]') == {"data-testid"}
    assert broken_attributes("#login-btn") == {"id"}
    assert broken_attributes("form [name='email']") == {"name"}
    renamed = _button_fp(attributes={"type": "submit", "data-testid": "login-button-v2"})
    with_testid, _ = score_fingerprint(_button_fp(), renamed)
    ignoring, _ = score_fingerprint(_button_fp(), renamed, frozenset({"data-testid"}))
    assert ignoring > with_testid
    assert ignoring == 1.0


def test_an_unchanged_id_survives_moving_and_wrapping():
    from engine.healer import ID_ANCHOR_SCORE

    moved = _button_fp(parent_chain=["div.field-wrap", "span.slot", "form#login-form"], sibling_index=4,
                       bounding_box=BoundingBox(x=600, y=900, width=200, height=40))
    score, _ = score_fingerprint(_button_fp(), moved, frozenset({"data-testid"}))
    assert score >= ID_ANCHOR_SCORE


def test_a_look_alike_sharing_no_identity_is_capped_below_the_threshold():
    from engine.healer import NO_IDENTITY_CAP

    stored = ElementFingerprint(tag="input", id="email", name="email", placeholder="Work email",
                                aria_label="Work email", attributes={"type": "email", "autocomplete": "email"},
                                parent_chain=["form"], sibling_index=1,
                                bounding_box=BoundingBox(x=10, y=10, width=200, height=30))
    twin = stored.model_copy(update={"id": "email-twin", "name": "email-twin", "placeholder": "Confirm work email",
                                     "aria_label": "Confirm work email"})
    score, _ = score_fingerprint(stored, twin, frozenset({"data-testid"}))
    assert score <= NO_IDENTITY_CAP
    same_but_renamed = stored.model_copy(update={"id": "x", "name": "y"})  # placeholder still identifies it
    assert score_fingerprint(stored, same_but_renamed, frozenset({"data-testid"}))[0] > NO_IDENTITY_CAP


def test_a_different_kind_of_input_is_never_the_same_element():
    box = ElementFingerprint(tag="input", id="remember", attributes={"type": "checkbox"})
    radio = box.model_copy(update={"attributes": {"type": "radio"}})
    email = ElementFingerprint(tag="input", id="email", attributes={"type": "email"})
    assert score_fingerprint(box, radio)[0] == 0.0
    assert score_fingerprint(email, email.model_copy(update={"attributes": {"type": "text"}}))[0] > 0.0
