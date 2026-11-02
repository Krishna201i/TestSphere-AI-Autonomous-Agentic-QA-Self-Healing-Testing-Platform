"""
Login and sign-up forms get their own tests (backend/services/auth_plan.py),
and the goal's sign-in only runs with what it needs.

Found by docs/generation-eval.md: a login with no goal was filled with made-up
credentials and passed without a check; "test the login" without credentials
failed on a working site; a sign-up reused one email and failed from the
second run on; a header search form's button was pressed instead of "Sign in".
"""

from __future__ import annotations

import pytest

from agents.analyzer.analyzer import FailureAnalyzerAgent
from agents.analyzer.schemas import FailureContext
from agents.memory.in_memory_store import InMemoryStore
from agents.schemas.enums import FailureType
from backend.services import auth_plan
from backend.services.url_analyzer import URLAnalyzerService as U
from engine.runner import with_unique_values
from engine.schemas import ActionType, Step, TestPlan

URL = "https://app.example/login"

LOGIN = """<header><form action="/search"><input type="search" name="q"><button type="submit">Search</button></form></header>
<main><form action="/login" method="post">
<input id="email" name="email" type="email" autocomplete="username" required>
<input id="password" name="password" type="password" autocomplete="current-password" required>
<button type="submit">Sign in</button></form></main>"""

SIGN_UP = """<form action="/signup" method="post">
<input id="name" name="name" required><input id="email" name="email" type="email" required>
<input id="password" name="password" type="password" required><input id="confirm" name="confirm" type="password" required>
<input id="terms" name="terms" type="checkbox" required><button type="submit">Create account</button></form>"""


def plan(html: str, prompt: str | None = None, **options):
    return U._plan_scenario(URL, "Page", U._extract_inputs(html), U._extract_buttons(html), prompt, **options)


def auth_tests(html: str, prompt: str | None = None, blocked: str | None = None) -> dict[str, list[dict]]:
    return {t["slug"]: t["steps"] for t in U._auth_tests(URL, U._extract_inputs(html), U._extract_buttons(html),
                                                          prompt, blocked)}


class TestFormChoice:
    def test_fields_and_buttons_know_their_form(self):
        inputs, buttons = U._extract_inputs(LOGIN), U._extract_buttons(LOGIN)
        assert [i["form"] for i in inputs] == [0, 1, 1]
        assert [(b["text"], b["form"]) for b in buttons] == [("Search", 0), ("Sign in", 1)]

    def test_the_password_form_is_filled_and_its_own_button_pressed(self):
        steps, _ = plan(LOGIN, "log in with demo@x.io / Secret-1")
        assert [s["target"] for s in steps if s["action"] == "FILL"] == ["#email", "#password"]  # not the search box
        assert next(s for s in steps if s["action"] == "CLICK")["target"] == "button:has-text('Sign in')"

    def test_a_search_goal_uses_the_search_form(self):
        html = '<form><input name="q" type="search"><button>Go</button></form><form><input name="a"><input name="b"><button>Save</button></form>'
        steps, _ = plan(html, 'search for "shoes"')
        assert [s["target"] for s in steps if s["action"] == "FILL"] == ["input[name='q']"]


class TestKind:
    @pytest.mark.parametrize(("html", "expected"), [
        (LOGIN, "login"),
        (SIGN_UP, "signup"),
        ('<input name="user"><input name="pw" type="password" autocomplete="new-password"><button>Go</button>', "signup"),
        ('<input name="e" type="email"><input name="p" type="password"><button>Register</button>', "signup"),
        ('<input name="first"><input name="e" type="email"><input name="p" type="password"><button>Go</button>', "signup"),
        ('<input name="q"><button>Go</button>', None),
    ])
    def test_kind_of_form(self, html, expected):
        inputs, buttons = U._form_of_goal(U._extract_inputs(html), U._extract_buttons(html), None)
        assert auth_plan.kind(inputs, None, buttons) == expected


class TestLogin:
    def test_without_credentials_the_sign_in_is_reported_not_run(self):
        steps, cov = plan(LOGIN, "test the login")
        assert [s["action"] for s in steps] == ["NAVIGATE"]  # no made-up credentials submitted
        assert cov == {"tested": [], "untested": ["test the login (needs credentials in the goal)"]}

    def test_without_a_goal_there_is_no_unchecked_interaction(self):
        steps, cov = plan(LOGIN)
        assert [s["action"] for s in steps] == ["NAVIGATE"] and cov == {"tested": [], "untested": []}

    def test_with_credentials_the_sign_in_must_leave_the_form_without_a_server_error(self):
        steps, cov = plan(LOGIN, "log in with demo@x.io / Secret-1")
        assert [s["action"] for s in steps][-3:] == ["CLICK", "ASSERT_HIDDEN", "ASSERT_HIDDEN"]
        assert steps[-2]["target"] == "#password" and steps[-1]["target"] == auth_plan.SERVER_ERROR
        assert cov["tested"] == ["log in with demo@x.io / Secret-1"]

    def test_every_login_gets_its_negative_tests(self):
        tests = auth_tests(LOGIN)
        assert set(tests) == {"auth-password-masked", "auth-empty-submit", "login-wrong-password"}
        wrong = tests["login-wrong-password"]
        assert [s["action"] for s in wrong] == ["NAVIGATE", "FILL", "FILL", "CLICK", "ASSERT_VISIBLE", "ASSERT_VISIBLE"]
        assert wrong[2]["value"] == auth_plan.WRONG_PASSWORD and wrong[3]["target"] == "button:has-text('Sign in')"
        assert wrong[4]["target"] == "#password" and wrong[5]["target"] == auth_plan.ERROR_SHOWN
        assert tests["auth-password-masked"][-1]["target"] == "#password[type=password]"
        assert [s["action"] for s in tests["auth-empty-submit"]] == ["NAVIGATE", "CLICK", "ASSERT_VISIBLE"]

    def test_the_wrong_password_test_uses_the_goals_user_and_never_its_password(self, monkeypatch):
        monkeypatch.setattr(auth_plan, "WRONG_PASSWORD", "Secret-1")  # what the goal's password happens to be
        tests = auth_tests(LOGIN, "log in with demo@x.io / Secret-1")
        fills = [s["value"] for s in tests["login-wrong-password"] if s["action"] == "FILL"]
        assert fills == ["demo@x.io", auth_plan.OTHER_PASSWORD]

    def test_a_captcha_leaves_out_every_submit_with_values(self):
        assert auth_plan.blocker('<div class="g-recaptcha" data-sitekey="x"></div>') == "a CAPTCHA blocks automated submits"
        assert auth_plan.blocker('<input autocomplete="one-time-code">') == "it asks for a one-time code"
        assert auth_plan.blocker(LOGIN) is None
        assert set(auth_tests(LOGIN, blocked="a CAPTCHA blocks automated submits")) == {"auth-password-masked",
                                                                                       "auth-empty-submit"}
        steps, cov = plan(LOGIN, "log in with demo@x.io / Secret-1", blocked="a CAPTCHA blocks automated submits")
        assert len(steps) == 1 and cov["untested"] == ["log in with demo@x.io / Secret-1 (a CAPTCHA blocks automated submits)"]


class TestSignUp:
    def test_without_test_accounts_no_account_is_created(self):
        steps, cov = plan(SIGN_UP, "sign up as a new user")
        assert [s["action"] for s in steps] == ["NAVIGATE"]
        assert cov["untested"] == ["sign up as a new user (test accounts are off for this project)"]

    def test_with_test_accounts_every_run_signs_up_someone_new(self):
        steps, _ = plan(SIGN_UP, None, allow_test_accounts=True, email_domain="qa.acme.dev")
        fills = {s["target"]: s["value"] for s in steps if s["action"] == "FILL"}
        assert fills == {"#name": "TestSphere QA", "#email": "qa+{{unique}}@qa.acme.dev",
                         "#password": auth_plan.TEST_PASSWORD, "#confirm": auth_plan.TEST_PASSWORD}
        assert ("CHECK", "#terms") in [(s["action"], s["target"]) for s in steps]
        assert [s["action"] for s in steps][-3:] == ["CLICK", "ASSERT_HIDDEN", "ASSERT_HIDDEN"]

    def test_every_sign_up_gets_its_negative_tests(self):
        tests = auth_tests(SIGN_UP)
        assert set(tests) == {"auth-password-masked", "auth-empty-submit", "signup-password-mismatch",
                              "signup-invalid-email"}
        mismatch = {s["target"]: s["value"] for s in tests["signup-password-mismatch"] if s["action"] == "FILL"}
        assert mismatch["#password"] != mismatch["#confirm"]
        invalid = tests["signup-invalid-email"]
        assert {s["target"]: s["value"] for s in invalid if s["action"] == "FILL"}["#email"] == auth_plan.INVALID_EMAIL
        assert "#email:invalid" in invalid[-1]["target"]  # the browser's own check counts as refusing it
        assert all("{{unique}}" not in str(s.get("value")) for t in tests.values() for s in t)  # never an account


class TestAfterSignIn:
    def planned(self, html, prompt=None, **options):
        return {t["slug"]: t for t in U._auth_tests(URL, U._extract_inputs(html), U._extract_buttons(html), prompt,
                                                     **options)}

    def test_with_credentials_the_session_is_checked_after_signing_in(self):
        tests = self.planned(LOGIN, "log in with demo@x.io / Secret-1")
        reload_ = tests["login-session-survives-reload"]["steps"]
        assert [s["action"] for s in reload_][-3:] == ["ASSERT_HIDDEN", "RELOAD", "ASSERT_HIDDEN"]
        assert [s["value"] for s in reload_ if s["action"] == "FILL"] == ["demo@x.io", "Secret-1"]
        logout = tests["login-logout"]
        assert [s["action"] for s in logout["steps"]][-5:] == ["CLICK", "ASSERT_HIDDEN", "GO_BACK", "RELOAD",
                                                               "ASSERT_HIDDEN"]
        assert logout["steps"][-1]["target"] == auth_plan.LOG_OUT
        assert logout.get("quarantined") and not tests["login-session-survives-reload"].get("quarantined")

    def test_without_credentials_or_behind_a_captcha_there_is_nothing_after_signing_in(self):
        assert not {"login-session-survives-reload", "login-logout"} & set(self.planned(LOGIN))
        blocked = self.planned(LOGIN, "log in with demo@x.io / Secret-1", blocked="a CAPTCHA blocks automated submits")
        assert set(blocked) == {"auth-password-masked", "auth-empty-submit"}

    def test_a_second_sign_up_with_the_same_email_must_be_refused(self):
        assert "signup-duplicate-email" not in self.planned(SIGN_UP)  # never without test accounts
        test = self.planned(SIGN_UP, allow_test_accounts=True, email_domain="qa.acme.dev")["signup-duplicate-email"]
        emails = [s["value"] for s in test["steps"] if s["target"] == "#email"]
        assert emails == ["qa+{{unique}}@qa.acme.dev"] * 2  # one run, one token: the same new email twice
        assert [s["action"] for s in test["steps"]][-3:] == ["ASSERT_VISIBLE", "ASSERT_VISIBLE", "ASSERT_HIDDEN"]
        assert test.get("quarantined")


def test_the_engine_gives_every_run_its_own_unique_value():
    plan_ = TestPlan(test_id="t", name="t", base_url="https://x.example", steps=[
        Step(step_id="a", action=ActionType.FILL, value="qa+{{unique}}@x.io"),
        Step(step_id="b", action=ActionType.ASSERT_TEXT, expected="qa+{{unique}}@x.io"),
    ])
    first, second = with_unique_values(plan_), with_unique_values(plan_)
    assert "{{unique}}" not in first.steps[0].value and first.steps[0].value == first.steps[1].expected
    assert first.steps[0].value != second.steps[0].value
    assert plan_.steps[0].value == "qa+{{unique}}@x.io"  # the stored plan is unchanged
    unchanged = TestPlan(test_id="t", name="t", base_url="https://x.example",
                         steps=[Step(step_id="a", action=ActionType.FILL, value="plain")])
    assert with_unique_values(unchanged) is unchanged


async def test_a_sign_in_form_still_shown_is_a_failed_check_not_a_hidden_element():
    analysis = await FailureAnalyzerAgent(InMemoryStore()).analyze(FailureContext(
        test_id="t", execution_id="e", action="assert_hidden", target_selector="#password",
        error_message="assert_hidden failed: '#password' is still visible"))
    assert analysis.failure_type == FailureType.ASSERTION_FAILURE
    assert "None" not in analysis.root_cause and "still visible" in analysis.root_cause
