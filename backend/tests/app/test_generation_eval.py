"""
The generation eval's site (tests/fixtures/auth_app.py) and report.

Every bug the eval switches on must really change what the site does: a
"missed" in docs/generation-eval.md has to mean the generated tests missed it,
never that the bug did nothing.  Plain HTTP, no browser.
"""

from __future__ import annotations

import httpx
import pytest

from scripts.generation_eval import (
    SCENARIOS,
    CaseOutcome,
    Scenario,
    ScenarioResult,
    feature_checks,
    write_report,
)
from tests.fixtures.auth_app import (
    BLOCKERS,
    MUTANTS,
    USER_EMAIL,
    USER_PASSWORD,
    AuthApp,
)

NEW_USER = {"name": "New Person", "email": "new@testsphere.test", "password": "Long-Enough-1",
            "confirm": "Long-Enough-1", "terms": "on"}


@pytest.fixture
def site():
    app = AuthApp()
    base = app.start()
    try:
        yield app, base
    finally:
        app.stop()


def _client(base: str) -> httpx.Client:
    return httpx.Client(base_url=base, follow_redirects=True, timeout=5)


def _login(c: httpx.Client, email: str = USER_EMAIL, password: str = USER_PASSWORD) -> httpx.Response:
    return c.post("/login", data={"email": email, "password": password})


def _signed_in(r: httpx.Response) -> bool:
    return r.url.path == "/account" and "Signed in as" in r.text


class TestHealthySite:
    def test_login_with_the_right_password_reaches_the_account(self, site):
        _, base = site
        with _client(base) as c:
            assert _signed_in(_login(c))
            assert _signed_in(c.get("/account"))  # the session holds on reload

    def test_wrong_password_keeps_the_form_and_says_why(self, site):
        _, base = site
        with _client(base) as c:
            r = _login(c, password="wrong")
            assert r.url.path == "/login" and 'role="alert"' in r.text and 'type="password"' in r.text

    def test_logout_ends_the_session(self, site):
        _, base = site
        with _client(base) as c:
            _login(c)
            c.get("/logout")
            assert c.get("/account").url.path == "/login"

    def test_signup_creates_the_account_once(self, site):
        app, base = site
        with _client(base) as c:
            assert c.post("/signup", data=NEW_USER).url.path == "/welcome"
            again = c.post("/signup", data=NEW_USER)
            assert again.url.path == "/signup" and "already exists" in again.text
        assert "new@testsphere.test" in app.users

    @pytest.mark.parametrize("change, message", [
        ({"confirm": "Different-1"}, "do not match"),
        ({"email": "not-an-email"}, "valid email"),
        ({"terms": ""}, "accept the terms"),
    ])
    def test_signup_refuses_bad_input(self, site, change, message):
        _, base = site
        with _client(base) as c:
            r = c.post("/signup", data={**NEW_USER, **change})
            assert r.url.path == "/signup" and message in r.text

    def test_store_login_puts_a_search_form_first(self, site):
        _, base = site
        with _client(base) as c:
            page = c.get("/store/login").text
            assert page.index(">Search</button>") < page.index(">Sign in</button>")

    def test_reset_forgets_new_users_and_sessions(self, site):
        app, base = site
        with _client(base) as c:
            c.post("/signup", data=NEW_USER)
            _login(c)
        app.reset()
        assert list(app.users) == [USER_EMAIL] and not app.sessions


# What each bug does, seen over HTTP: the healthy site must not do it
def _bug_shows(name: str, c: httpx.Client) -> bool:
    if name == "login-rejects-valid":
        return not _signed_in(_login(c))
    if name == "login-accepts-wrong-password":
        return _signed_in(_login(c, password="wrong"))
    if name == "login-no-error-message":
        return 'role="alert"' not in _login(c, password="wrong").text
    if name == "login-empty-submit":
        page = c.get("/login").text
        return " required" not in page and _signed_in(_login(c, "", ""))
    if name == "password-visible":
        return 'type="password"' not in c.get("/login").text
    if name == "session-lost-on-reload":
        return _signed_in(_login(c)) and not _signed_in(c.get("/account"))
    if name == "logout-broken":
        _login(c)
        c.get("/logout")
        return _signed_in(c.get("/account"))
    if name == "signup-broken":
        return c.post("/signup", data=NEW_USER).status_code == 500
    if name == "signup-mismatch-accepted":
        return c.post("/signup", data={**NEW_USER, "confirm": "Different-1"}).url.path == "/welcome"
    if name == "signup-invalid-email-accepted":
        return c.post("/signup", data={**NEW_USER, "email": "not-an-email"}).url.path == "/welcome"
    if name == "signup-duplicate-crash":
        return c.post("/signup", data={**NEW_USER, "email": USER_EMAIL}).status_code == 500
    if name == "signup-no-confirmation":
        r = c.post("/signup", data=NEW_USER)
        return r.url.path == "/signup" and 'role="alert"' not in r.text
    if name == "captcha":
        page = c.get("/login").text
        return "g-recaptcha" in page and not _signed_in(_login(c))
    raise AssertionError(f"no check for {name}")


@pytest.mark.parametrize("name", [*MUTANTS, *BLOCKERS])
def test_every_switch_changes_what_the_site_does(site, name):
    app, base = site
    with _client(base) as c:
        assert not _bug_shows(name, c), "the healthy site already behaves like the bug"
    app.reset()
    app.set_mutant(name)
    with _client(base) as c:
        assert _bug_shows(name, c)


def test_an_unknown_switch_is_refused():
    with pytest.raises(ValueError):
        AuthApp().set_mutant("no-such-bug")


def test_feature_checks_ignore_render_and_title_checks():
    steps = [
        {"action": "NAVIGATE", "value": "http://x"},
        {"action": "ASSERT_VISIBLE", "target": "body"},
        {"action": "ASSERT_CONTAINS_TEXT", "target": "head > title", "value": "Sign in"},
        {"action": "ASSERT_HIDDEN", "target": "#password"},
    ]
    assert feature_checks(steps) == 1
    assert feature_checks(steps[:3]) == 0


def test_every_scenario_names_a_flow_with_bugs():
    assert len({s.key for s in SCENARIOS}) == len(SCENARIOS)
    for s in SCENARIOS:
        assert any(info["page"] == s.flow for info in MUTANTS.values()), s.key


def test_report_counts_caught_bugs_and_false_failures(tmp_path):
    scenario = Scenario("login-x", "/login", None, "login", "Note.")
    login_bugs = [m for m, info in MUTANTS.items() if info["page"] == "login"]
    runs = {"healthy-1": (True, ""), "healthy-2": (False, "assert_hidden failed")}
    runs |= {m: (True, "") for m in login_bugs} | {login_bugs[0]: (False, "caught it")}
    weak = CaseOutcome("smoke", "Smoke", 0, {k: (True, "") for k in runs})
    strong = CaseOutcome("interaction", "Interaction", 1, runs)
    on_captcha = [CaseOutcome("smoke", "Smoke", 0, {"captcha": (False, "blocked")})]
    result = ScenarioResult(scenario, [weak, strong], 1.0, {"captcha": on_captcha})

    assert result.caught(login_bugs[0]) and not result.caught(login_bugs[1])
    assert result.healthy_failures("healthy-2") == 1 and result.blocked_failures("captcha") == 1

    md, csv_path = tmp_path / "eval.md", tmp_path / "eval.csv"
    write_report([result], md, csv_path)
    text = md.read_text(encoding="utf-8")
    assert f"| `login-x` | 2 | 1 | 0 / 1 | 1 of {len(login_bugs)} (14%) | 1 |" in text
    assert "**fail**: assert_hidden failed" in text
    assert "With a captcha on the form: Smoke: **fail** (blocked)." in text
    assert len(csv_path.read_text(encoding="utf-8").splitlines()) == 1 + 2 * len(runs) + 1
