"""Plain-English phrases the rule-based planner understands (Test Studio without an AI model)."""

from __future__ import annotations

import pytest

from app.services.goal_plan import (
    ERROR_MESSAGE,
    expects_failure,
    later_part_steps,
    plan_goal,
    split_goal,
)
from app.services.url_analyzer import URLAnalyzerService

values = URLAnalyzerService.prompt_values


@pytest.mark.parametrize(("text", "expected"), [
    ("Log in with demo@x.test and password Secret-1 and check it works", {"username": "demo@x.test", "password": "Secret-1"}),
    ("log in with tomsmith / SuperSecretPassword!", {"username": "tomsmith", "password": "SuperSecretPassword!"}),
    ("log in as standard_user / secret_sauce", {"username": "standard_user", "password": "secret_sauce"}),
    ("username student and password Password123", {"username": "student", "password": "Password123"}),
    ("Sign up with name Ann Lee, email ann@x.test, password P-1 and confirm Q-2",
     {"username": "ann@x.test", "password": "P-1", "confirm": "Q-2", "name": "Ann Lee"}),
])
def test_values_in_natural_phrasing(text, expected):
    got = values(text)
    assert {k: got.get(k) for k in expected} == expected


def test_a_path_is_not_user_slash_password():
    got = values("log in with demo@x.test and password P-1, click Log out, open /account")
    assert got["username"] == "demo@x.test" and got["password"] == "P-1"


def test_confirm_and_terms_stay_with_the_form_but_a_check_does_not():
    assert split_goal("Sign up with email a@b.test, password P-1, confirm P-1, accept the terms and check the page "
                      "shows Account created") == [
        "Sign up with email a@b.test and password P-1 and confirm P-1 and accept the terms",
        "check the page shows Account created"]
    assert split_goal("log in with a@b.test and password P-1, confirm the page shows Welcome")[1] == \
        "confirm the page shows Welcome"


@pytest.mark.parametrize(("part", "action", "target", "value"), [
    ("check the page shows Signed in as demo", "ASSERT_CONTAINS_TEXT", "body", "Signed in as demo"),
    ("make sure it still displays Your account", "ASSERT_CONTAINS_TEXT", "body", "Your account"),
    ("check the page does not show Account created", "ASSERT_HIDDEN", 'internal:text="Account created"i', None),
    ("check that an error message is shown", "ASSERT_VISIBLE", ERROR_MESSAGE, None),
    ("check the password field hides what is typed", "ASSERT_VISIBLE", "input[type=password]", None),
    ("reload the page", "RELOAD", None, None),
    ("go back", "GO_BACK", None, None),
    ("open /account", "NAVIGATE", None, "/account"),
])
def test_later_parts(part, action, target, value):
    [step] = later_part_steps(1, part, {})
    assert (step["action"], step["target"], step["value"]) == (action, target, value)


def test_click_ignores_a_trailing_qualifier():
    [step] = later_part_steps(1, "Click Sign in without filling anything", {})
    assert step["target"].endswith(':has-text("Sign in")')


@pytest.mark.parametrize(("part", "refused"), [
    ("check an error message is shown", True),
    ("check the page does not show Account created", True),
    ("check the page shows already exists", True),
    ("check the page shows Account created", False),
    ("click Log out", False),
])
def test_what_counts_as_expecting_a_refusal(part, refused):
    assert expects_failure(part) is refused


PASSWORD_INPUT = [{"selector": "#password", "type": "password", "name": "password"}]


def test_a_refused_login_is_not_asserted_to_succeed():
    steps, _ = plan_goal("log in with a@b.test and password wrong-1 and check an error message is shown",
                         PASSWORD_INPUT, {"username": "a@b.test", "password": "wrong-1"}, form_used=True, first_step=1)
    assert [s["action"] for s in steps] == ["ASSERT_VISIBLE"] and steps[0]["target"] == ERROR_MESSAGE


def test_a_later_negative_check_does_not_cancel_the_login_check():
    steps, _ = plan_goal("log in with a@b.test and password P-1, click Log out and check the page does not show Signed in",
                         PASSWORD_INPUT, {"username": "a@b.test", "password": "P-1"}, form_used=True, first_step=1)
    assert steps[0] == {"step_number": 1, "action": "ASSERT_HIDDEN", "target": "#password", "value": None,
                        "description": "the sign-in form (it should be gone after signing in)"}
    assert [s["action"] for s in steps][-2:] == ["CLICK", "ASSERT_HIDDEN"]


def test_benchmark_scores_a_bug_caught_by_a_false_alarm_as_missed():
    from scripts.studio_eval import CASES, CaseResult, summary

    good = CaseResult(CASES[0], saveable=True, healthy=(True, ""), caught={"login-rejects-valid": True})
    noisy = CaseResult(CASES[1], saveable=True, healthy=(False, "boom"),
                       caught={"login-accepts-wrong-password": True, "login-no-error-message": True})
    s = summary([good, noisy])
    assert (s["caught"], s["bugs"], s["false_alarms"]) == (1, 3, 1)
