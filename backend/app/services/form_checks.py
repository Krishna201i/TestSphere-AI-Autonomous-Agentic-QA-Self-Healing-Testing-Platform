"""
TestSphere-AI — Negative tests for a page's forms (input that must be refused).

Input-space partitioning, the way testers pick negative cases: for each form
the page has, one test submits it with its required fields empty and one with
an email field holding something that is not an email.  The oracle is the
browser's own constraint validation: the field must be ``:invalid`` after the
submit, which a healthy form always is (so these never fail a working site),
and a form that stopped validating (``required`` dropped, an email field
turned into plain text) fails them.

Only forms the browser validates (no ``novalidate``) get them, and never a
login or sign-up form: those have their own negative tests (``auth_plan``).
"""

from __future__ import annotations

import re
from typing import Any

from app.services import auth_plan

MAX_FORMS = 2
_TEXT_LIKE = {"text", "email", "password", "search", "tel", "url", "number", "textarea", None, ""}


def _step(action: str, description: str, *, target: str | None = None, value: str | None = None) -> dict[str, Any]:
    return {"action": action, "target": target, "value": value, "description": description}


def _numbered(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"step_number": i, **s} for i, s in enumerate(steps, start=1)]


def validated_forms(html: str) -> list[bool]:
    """For each <form> of *html* in page order: whether the browser validates it."""
    return [not re.search(r"\bnovalidate\b", tag, re.IGNORECASE)
            for tag in re.findall(r"<form\b[^>]*>", html, re.IGNORECASE)]


def _submit_of(buttons: list[dict[str, Any]], form: int) -> dict[str, Any] | None:
    own = [b for b in buttons if b.get("form") == form and b.get("selector") not in (None, "button")]
    return next((b for b in own if b.get("type") == "submit"), None)


def negative_tests(url: str, inputs: list[dict[str, Any]], buttons: list[dict[str, Any]], html: str,
                   prompt: str | None = None) -> list[dict[str, Any]]:
    """Negative tests for the page's validated forms (at most ``MAX_FORMS``)."""
    validated = validated_forms(html)
    tests: list[dict[str, Any]] = []
    forms = sorted({i.get("form") for i in inputs if i.get("form") is not None})
    for form in forms:
        if len(tests) >= MAX_FORMS * 2 or form >= len(validated) or not validated[form]:
            continue
        fields = [i for i in inputs if i.get("form") == form]
        if auth_plan.kind(fields, prompt, [b for b in buttons if b.get("form") == form]):
            continue  # a login or sign-up form has its own negative tests
        submit = _submit_of(buttons, form)
        if submit is None:
            continue
        suffix = "" if form == forms[0] else f"-{form}"
        press = _step("CLICK", f"the '{submit.get('text') or 'submit'}' button", target=submit["selector"])
        required = [i for i in fields if i.get("required") and i.get("type") in _TEXT_LIKE]
        if required:
            steps = [_step("NAVIGATE", f"Open {url}", value=url), press]
            steps += [_step("ASSERT_VISIBLE", f"'{_label(f)}' is flagged as missing (the form was not sent)",
                            target=f"{f['selector']}:invalid") for f in required[:3]]
            tests.append({"slug": f"form-required-empty{suffix}", "category": "functional", "steps": _numbered(steps),
                          "name": f"Form refuses empty required fields: {', '.join(_label(f) for f in required[:3])}"})
        email = next((i for i in fields if i.get("type") == "email"), None)
        if email:
            steps = [_step("NAVIGATE", f"Open {url}", value=url),
                     _step("FILL", f"'{_label(email)}' with something that is not an email", target=email["selector"],
                           value="not-an-email"),
                     press,
                     _step("ASSERT_VISIBLE", f"'{_label(email)}' is flagged as not an email address",
                           target=f"{email['selector']}:invalid")]
            tests.append({"slug": f"form-invalid-email{suffix}", "category": "functional", "steps": _numbered(steps),
                          "name": f"Form refuses an invalid email in '{_label(email)}'"})
    return tests


def _label(field: dict[str, Any]) -> str:
    return str(field.get("aria_label") or field.get("placeholder") or field.get("name") or field.get("id")
               or field.get("type") or "field")[:40]
