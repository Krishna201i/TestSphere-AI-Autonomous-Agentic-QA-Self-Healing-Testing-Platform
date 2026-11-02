"""
TestSphere-AI — Tests for a login or sign-up form.

``URLAnalyzerService`` finds the page's fields; this module decides what kind
of form holds the password field and which tests it gets:

* **login**: a wrong password is refused with a message, an empty form is not
  sent, the password is masked.  The real sign-in (``-interaction``) runs only
  when the goal gives credentials; without them it is reported as not tested,
  never run with invented credentials that are bound to fail.
  With credentials it also checks what comes after signing in: the session
  survives a reload, and logging out ends it (Back and reload do not show the
  signed-in page again).
* **sign-up**: different passwords and an invalid email are refused.  Creating
  a real account runs only when the project allows test accounts, with a new
  email every run (``{{unique}}``, filled in by the engine); then signing up
  again with that email must be refused, not crash.

Tests that assume something of the app the page analysis cannot see (a
visible "Log out" control, a sign-up page that stays open after signing up)
start quarantined: they run and report, but cannot fail a run until someone
confirms they fit the app.

A CAPTCHA or a one-time code on the page blocks automated submits: those tests
are left out and reported instead of failing the site.

Pure functions; steps have the pipeline's shape (see ``goal_plan``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

UNIQUE = "{{unique}}"  # replaced by the engine with a token new on every run

WRONG_PASSWORD = "Wrong-Password-41!"
TEST_PASSWORD = "TestSphere-Qa-2026!"
OTHER_PASSWORD = "Different-Qa-2026!"
INVALID_EMAIL = "not-an-email"
DEFAULT_EMAIL_DOMAIN = "example.com"

# A message the page shows when it refuses what was sent
_ERROR_PARTS = ('[role=alert], [aria-live=assertive], .error, .errors, .alert-danger, .invalid-feedback, '
                '.field-error, .form-error, [class*="error" i]')
ERROR_SHOWN = f":is({_ERROR_PARTS}):visible"
# A server error page instead of the result
SERVER_ERROR = (':is(h1, h2, h3, p, [role=alert]):text-matches("internal server error|something went wrong|'
                'unexpected error|bad gateway|service unavailable|^\\\\s*50[0-4]\\\\b", "i")')
# The control that signs out, as a person sees it
LOG_OUT = (':is(a, button, [role=button], [role=menuitem]):text-matches("^\\\\s*(?:log ?out|sign ?out|log off)\\\\s*$", "i")'
           ':visible')

_CAPTCHA = re.compile(r"g-recaptcha|recaptcha/api|h-captcha|hcaptcha\.com|cf-turnstile|challenges\.cloudflare\.com",
                      re.IGNORECASE)
_ONE_TIME_CODE = re.compile(r"autocomplete\s*=\s*[\"']one-time-code", re.IGNORECASE)
_CONFIRM = re.compile(r"confirm|repeat|again|retype|verify|password2|passwordconfirm", re.IGNORECASE)
_SIGN_UP_GOAL = re.compile(r"\b(?:sign ?up|register|create (?:an |a new |my )?account|join)\b", re.IGNORECASE)

Step = dict[str, Any]
FillSteps = Callable[[list[dict[str, Any]], dict[str, str]], list[Step]]


def _hint(field: dict[str, Any]) -> str:
    return " ".join(str(field.get(k) or "") for k in ("name", "id", "placeholder", "aria_label", "autocomplete")).lower()


def is_password(field: dict[str, Any]) -> bool:
    return field.get("type") == "password" or ("pass" in _hint(field) and field.get("type") in ("text", None))


def is_confirm(field: dict[str, Any]) -> bool:
    return is_password(field) and bool(_CONFIRM.search(_hint(field)))


def blocker(html: str) -> str | None:
    """Why submits cannot be automated on this page, or None."""
    if _CAPTCHA.search(html or ""):
        return "a CAPTCHA blocks automated submits"
    if _ONE_TIME_CODE.search(html or ""):
        return "it asks for a one-time code"
    return None


_TEXT_FIELD = ("text", "email", "tel", "number", "date", "url", "textarea", "select", None)


def kind(inputs: list[dict[str, Any]], prompt: str | None = None,
         buttons: list[dict[str, Any]] | None = None) -> str | None:
    """'signup', 'login' or None for the form these fields belong to.

    A sign-up asks for the password twice or as a new one, says so on its
    button or in the goal, or asks for more than one thing besides the
    password (a login asks for one: the user name or email).
    """
    passwords = [f for f in inputs if is_password(f)]
    if not passwords:
        return None
    others = [f for f in inputs if not is_password(f) and f.get("type") in _TEXT_FIELD]
    if (len(passwords) > 1 or any(is_confirm(f) for f in passwords)
            or any("new-password" in _hint(f) for f in passwords)
            or any(_SIGN_UP_GOAL.search(str(b.get("text") or "")) for b in buttons or [])
            or (prompt and _SIGN_UP_GOAL.search(prompt))
            or len(others) > 1):
        return "signup"
    return "login"


def _step(action: str, description: str, *, target: str | None = None, value: str | None = None) -> Step:
    return {"step_number": 0, "action": action, "target": target, "value": value, "description": description}


def _numbered(steps: list[Step]) -> list[Step]:
    return [{**s, "step_number": i} for i, s in enumerate(steps, start=1)]


def _submit(button: dict[str, Any] | None, fill: list[Step]) -> Step | None:
    if button:
        return _step("CLICK", f"the '{button.get('text') or 'submit'}' button", target=button["selector"])
    fields = [s for s in fill if s["action"] == "FILL"]
    if fields:
        return _step("PRESS", fields[-1]["description"], target=fields[-1]["target"], value="Enter")
    return None


def _test(slug: str, name: str, steps: list[Step], *, quarantined: bool = False) -> dict[str, Any]:
    test = {"slug": slug, "name": name, "category": "functional", "steps": _numbered(steps)}
    if quarantined:
        test["quarantined"] = True
    return test


def still_on_form(password: dict[str, Any]) -> Step:
    return _step("ASSERT_VISIBLE", "the form is still there (it was not accepted)", target=password["selector"])


def success_steps(password: dict[str, Any]) -> list[Step]:
    """After a form that should be accepted: it is gone, and no server error took its place."""
    return [
        _step("ASSERT_HIDDEN", "the form is gone (it was accepted)", target=password["selector"]),
        _step("ASSERT_HIDDEN", "no server error is shown", target=SERVER_ERROR),
    ]


def signup_values(email_domain: str | None) -> dict[str, str]:
    """Values for a sign-up that creates a new account every run."""
    domain = (email_domain or DEFAULT_EMAIL_DOMAIN).strip().lstrip("@") or DEFAULT_EMAIL_DOMAIN
    return {"username": f"qa{UNIQUE}", "email": f"qa+{UNIQUE}@{domain}", "name": "TestSphere QA",
            "password": TEST_PASSWORD, "confirm": TEST_PASSWORD}


def negative_tests(form_kind: str, url: str, inputs: list[dict[str, Any]], button: dict[str, Any] | None,
                   given: dict[str, str], fill: FillSteps, *, blocked: bool) -> list[dict[str, Any]]:
    """The tests every login or sign-up form gets, with or without credentials."""
    password = next((f for f in inputs if is_password(f)), None)
    if password is None:
        return []
    open_page = _step("NAVIGATE", f"Open {url}", value=url)
    tests: list[dict[str, Any]] = []
    if password.get("type") == "password":
        tests.append(_test("auth-password-masked", "Login: the password is masked" if form_kind == "login"
                           else "Sign-up: the password is masked", [
                               open_page,
                               _step("ASSERT_VISIBLE", "the password field hides what is typed",
                                     target=f"{password['selector']}[type=password]"),
                           ]))
    submit = _submit(button, [])
    if submit and submit["action"] == "CLICK":
        tests.append(_test("auth-empty-submit", "Login: an empty form is not sent" if form_kind == "login"
                           else "Sign-up: an empty form is not sent", [open_page, submit, still_on_form(password)]))
    if blocked:
        return tests  # a submit with values is refused by the CAPTCHA whatever the form does

    if form_kind == "login":
        values = {"username": given.get("username") or "qa_user@testsphere.ai", "password": WRONG_PASSWORD}
        if values["password"] == given.get("password"):
            values["password"] = OTHER_PASSWORD
        steps = fill(inputs, values)
        submit = _submit(button, steps)
        if submit:
            tests.append(_test("login-wrong-password", "Login: a wrong password is refused with a message", [
                open_page, *steps, submit, still_on_form(password),
                _step("ASSERT_VISIBLE", "an error message is shown", target=ERROR_SHOWN),
            ]))
        return tests

    # sign-up: valid values except one, never an account (the email is fixed: it is refused anyway)
    base = {**signup_values(None), "username": "qa_user", "email": "qa_user@example.com"}
    if sum(1 for f in inputs if is_password(f)) > 1:
        steps = fill(inputs, {**base, "confirm": OTHER_PASSWORD})
        submit = _submit(button, steps)
        if submit:
            tests.append(_test("signup-password-mismatch", "Sign-up: different passwords are refused", [
                open_page, *steps, submit, still_on_form(password),
                _step("ASSERT_VISIBLE", "an error message is shown", target=ERROR_SHOWN),
            ]))
    email = next((f for f in inputs if f.get("type") == "email" or "mail" in _hint(f)), None)
    if email:
        steps = fill(inputs, {**base, "email": INVALID_EMAIL})
        submit = _submit(button, steps)
        if submit:
            refused = f":is({_ERROR_PARTS}, {email['selector']}:invalid):visible"
            tests.append(_test("signup-invalid-email", "Sign-up: an invalid email is refused", [
                open_page, *steps, submit, still_on_form(password),
                _step("ASSERT_VISIBLE", "the email is marked as invalid", target=refused),
            ]))
    return tests


def after_sign_in_tests(form_kind: str, url: str, inputs: list[dict[str, Any]], button: dict[str, Any] | None,
                        given: dict[str, str], fill: FillSteps, *, allow_test_accounts: bool = False,
                        email_domain: str | None = None) -> list[dict[str, Any]]:
    """What comes after a sign-in or sign-up that works (callers leave these
    out behind a CAPTCHA): a login needs the goal's credentials, a sign-up
    needs test accounts allowed."""
    password = next((f for f in inputs if is_password(f)), None)
    if password is None:
        return []
    open_page = _step("NAVIGATE", f"Open {url}", value=url)

    if form_kind == "login":
        if not (given.get("username") and given.get("password")):
            return []
        steps = fill(inputs, {"username": given["username"], "password": given["password"]})
        submit = _submit(button, steps)
        if submit is None:
            return []
        sign_in = [open_page, *steps, submit,
                   _step("ASSERT_HIDDEN", "signed in (the sign-in form is gone)", target=password["selector"])]
        return [
            _test("login-session-survives-reload", "Login: the session survives a reload", [
                *sign_in,
                _step("RELOAD", "reload the signed-in page"),
                _step("ASSERT_HIDDEN", "still signed in (not sent back to sign in)", target=password["selector"]),
            ]),
            # Assumes a visible "Log out" on the page after signing in
            _test("login-logout", "Login: logging out ends the session", [
                *sign_in,
                _step("CLICK", "the 'Log out' control", target=LOG_OUT),
                _step("ASSERT_HIDDEN", "signed out (no 'Log out' any more)", target=LOG_OUT),
                _step("GO_BACK", "Back to the signed-in page"),
                _step("RELOAD", "reload it, as the server sees it now"),
                _step("ASSERT_HIDDEN", "still signed out (the signed-in page is not shown again)", target=LOG_OUT),
            ], quarantined=True),
        ]

    if not allow_test_accounts:
        return []
    values = signup_values(email_domain)
    steps = fill(inputs, values)
    submit = _submit(button, steps)
    if submit is None:
        return []
    # Assumes the sign-up page can be opened again right after signing up
    return [_test("signup-duplicate-email", "Sign-up: an email already registered is refused", [
        open_page, *steps, submit, *success_steps(password),
        _step("NAVIGATE", f"Open {url} again", value=url), *steps, submit,
        still_on_form(password),
        _step("ASSERT_VISIBLE", "an error message is shown", target=ERROR_SHOWN),
        _step("ASSERT_HIDDEN", "no server error is shown", target=SERVER_ERROR),
    ], quarantined=True)]
