"""
TestSphere-AI — The written goal, part by part, as steps that check their outcome.

A goal like "log in as standard_user with password secret_sauce and add the
backpack to the cart" has two parts.  The page analysis covers the first (the
form: fill and submit).  This module

* adds an **outcome check** after the form, so a failed sign-in fails the test
  instead of passing because the button could be clicked;
* turns the **later parts** into steps that find their element by its text at
  run time (the page they act on has not been analyzed), each followed by a
  check that it took effect;
* reports every part it could **not** turn into steps, so a run never claims a
  goal it only partly tested.

Pure functions; selectors use Playwright's ``:has-text()`` (case-insensitive,
substring) inside CSS ``:has()``/``:not()``.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.auth_plan import SERVER_ERROR

# Parts of a goal: split on "and"/"then"/commas, but "username X and password Y" stays one part
_SPLIT = re.compile(r"\s*(?:,\s*(?:and\s+|then\s+)?|;\s*|\s+and then\s+|\s+then\s+|\s+and\s+)", re.IGNORECASE)
_FORM_VERB = re.compile(r"^(?:log ?in|sign ?in|search|type|enter|fill|submit)\b", re.IGNORECASE)
_CREDENTIAL = re.compile(r"^(?:(?:the|my|a)\s+)?(?:pass(?:word)?|user ?name|user|e-?mail|login)\b"
                         # "confirm Other-Pass-99" (one value, not "confirm the page shows ..."), "accept the terms"
                         r"|^confirm(?:ation)?(?:\s+(?:the\s+)?password)?\s+(?:with\s+)?\S+$"
                         r"|^(?:accept|agree\s+to|tick)\s+(?:the\s+)?(?:terms|conditions|privacy)", re.IGNORECASE)
_ARTICLE = re.compile(r"^(?:the|a|an|my|your|this|that)\s+", re.IGNORECASE)

_CONTAINER = ":is(li,tr,td,article,section,form,div)"
_ACTIONABLE = ":is(button,a,[role=button],[role=link],[role=tab],[role=menuitem],input[type=button],input[type=submit])"


def split_goal(prompt: str | None) -> list[str]:
    """The goal's parts, each starting with what to do."""
    text = re.sub(r"\b(?:https?://|www\.)\S+", " ", prompt or "").strip().rstrip(".!")
    parts: list[str] = []
    for piece in (p.strip() for p in _SPLIT.split(text) if p and p.strip()):
        if parts and _CREDENTIAL.match(piece):
            parts[-1] = f"{parts[-1]} and {piece}"  # "password Y" belongs to "log in with username X"
        else:
            parts.append(piece)
    return parts


def is_form_part(part: str, values: dict[str, str]) -> bool:
    """Done by filling and submitting the analyzed page's form."""
    if _FORM_VERB.match(part):
        return True
    text = values.get("text")
    return bool(text and re.match(r"^(?:add|create|post|write)\b", part, re.IGNORECASE) and text.lower() in part.lower())


def _quote(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _noun(text: str) -> str:
    text = _ARTICLE.sub("", text.strip().strip("\"'“”"))
    return re.sub(r"\s+(?:item|button|link|tab|checkbox|box)$", "", text, flags=re.IGNORECASE).strip()


def _innermost(name: str, inner: str) -> str:
    """The smallest block showing *name* that holds an *inner* control, then that control."""
    block = f'{_CONTAINER}:has-text("{_quote(name)}"):has({inner})'
    return f"{block}:not(:has({block})) {inner}"


def _step(n: int, action: str, description: str, *, target: str | None = None, value: str | None = None) -> dict[str, Any]:
    return {"step_number": n, "action": action, "target": target, "value": value, "description": description}


def form_outcome(n: int, part: str, inputs: list[dict[str, Any]], values: dict[str, str]) -> list[dict[str, Any]]:
    """After the form is submitted: did it work?"""
    password = next((i for i in inputs if i.get("type") == "password"
                     or "pass" in f"{i.get('name', '')} {i.get('id', '')}".lower()), None)
    if password:
        return [
            _step(n, "ASSERT_HIDDEN", "the sign-in form (it should be gone after signing in)", target=password["selector"]),
            _step(n + 1, "ASSERT_HIDDEN", "no server error is shown", target=SERVER_ERROR),
        ]
    text = values.get("text")
    if text and re.match(r"^(?:add|create|post|write)\b", part, re.IGNORECASE):
        return [_step(n, "ASSERT_CONTAINS_TEXT", f"the new item '{text[:40]}' shows on the page",
                      target="body", value=text)]
    return []


def no_server_error(n: int) -> dict[str, Any]:
    """The implicit check after a submit whose success nobody described: no
    server error page (true of every healthy app, so it never fails one)."""
    return _step(n, "ASSERT_HIDDEN", "no server error is shown", target=SERVER_ERROR)


# An error or validation message, as sites show them
ERROR_MESSAGE = (':is([role=alert],[aria-live=assertive],.error,.errors,.alert-danger,.alert-error,.invalid-feedback,'
                 '.field-error,.form-error,[aria-invalid=true])')
_CHECK = r"^(?:check|verify|confirm|ensure|make sure|expect|see)\s+(?:that\s+)?"
_SUBJECT = r"(?:the\s+page|the\s+screen|it|page|there)?\s*(?:still\s+)?"
_ERROR_PART = re.compile(_CHECK + r"(?:an?\s+|the\s+)?(?:error|validation)(?:\s+message)?\s+(?:is\s+|gets\s+)?"
                         r"(?:shown|displayed|visible|appears?)$", re.IGNORECASE)
_NOT_SHOWN = re.compile(_CHECK + _SUBJECT + r"(?:does\s*n[o']t|does not|did not|no longer|never)\s+"
                        r"(?:shows?|displays?|contains?)\s+(.+)$", re.IGNORECASE)
_SHOWN = re.compile(_CHECK + _SUBJECT + r"(?:shows?|displays?|contains?|says)\s+(.+)$", re.IGNORECASE)
_HIDES_PASSWORD = re.compile(_CHECK + r"(?:the\s+)?password(?:\s+field)?\s+(?:hides|masks)\b", re.IGNORECASE)


_REFUSAL_WORDS = re.compile(r"\b(?:already|exists?|invalid|incorrect|wrong|error|failed|denied|not\s+(?:valid|allowed|found|match)"
                            r"|taken|required|must|cannot|can't|unable|mismatch|do(?:es)?\s*n[o']t\s+match)\b", re.IGNORECASE)


def expects_failure(part: str) -> bool:
    """A part that expects the form to be refused: an error, a page that must not
    appear, or a message that says why ("check the page shows already exists")."""
    p = part.strip()
    if _ERROR_PART.match(p) or _NOT_SHOWN.match(p):
        return True
    m = _SHOWN.match(p)
    return bool(m and _REFUSAL_WORDS.search(m.group(1)))


def _shown_text(raw: str) -> str:
    """Text the page must show, exactly as written: "Your account" is not "account" (which a
    signed-out page saying "Sign in to your account" also shows)."""
    return raw.strip().strip("\"'“”").rstrip(".").strip()


def later_part_steps(n: int, part: str, values: dict[str, str]) -> list[dict[str, Any]]:
    """Steps for one part after the form; [] when it cannot be turned into steps."""
    p = part.strip()
    if re.match(r"^(?:check|verify|confirm|see)\b.*\b(?:loads?|opens?|works?|renders?)$", p, re.IGNORECASE):
        return [_step(n, "ASSERT_VISIBLE", "the page loads", target="body")]
    if re.match(r"^(?:reload|refresh)(?:\s+the\s+page)?$", p, re.IGNORECASE):
        return [_step(n, "RELOAD", "reload the page")]
    if re.match(r"^go\s+back$", p, re.IGNORECASE):
        return [_step(n, "GO_BACK", "go back")]
    if _ERROR_PART.match(p):
        return [_step(n, "ASSERT_VISIBLE", "an error message is shown", target=ERROR_MESSAGE)]
    if _HIDES_PASSWORD.match(p):
        return [_step(n, "ASSERT_VISIBLE", "the password field hides what is typed", target="input[type=password]")]
    m = _NOT_SHOWN.match(p)
    if m and (what := _shown_text(m.group(1))):
        return [_step(n, "ASSERT_HIDDEN", f"the page does not show '{what[:60]}'",
                      target=f'internal:text="{_quote(what)}"i')]
    m = _SHOWN.match(p)
    if m and (what := _shown_text(m.group(1))):
        return [_step(n, "ASSERT_CONTAINS_TEXT", f"the page shows '{what[:60]}'", target="body", value=what)]
    m = re.match(r"^(?:reach|see|verify|confirm|expect|land on|get to|view)\s+(?:that\s+)?(.+)$", p, re.IGNORECASE)
    if m:
        what = _noun(re.sub(r"\s+(?:page|screen)$", "", m.group(1), flags=re.IGNORECASE))
        return [_step(n, "ASSERT_CONTAINS_TEXT", f"the page shows '{what[:60]}'", target="body", value=what)] if what else []

    m = re.match(r"^add\s+(.+?)\s+to\s+(?:the\s+|my\s+)?(?:shopping\s+)?(cart|basket|bag)\b", p, re.IGNORECASE)
    if m:
        item, place = _noun(m.group(1)), m.group(2).lower()
        # Once added, the cart shows a count (a badge like "1" or "Cart (1)")
        count = f':is([class*="{place}" i],[id*="{place}" i],[aria-label*="{place}" i]):text-matches("[1-9]")'
        return [
            _step(n, "CLICK", f"the Add button for '{item[:40]}'", target=_innermost(item, f'{_ACTIONABLE}:has-text("add")')),
            _step(n + 1, "ASSERT_VISIBLE", f"the {place} shows a count", target=count),
        ]

    m = re.match(r"^(?:mark|tick|check)\s+(.+?)\s+(?:as\s+)?(?:completed?|done|finished|checked)$", p, re.IGNORECASE)
    if m:
        item = _noun(m.group(1))
        if item.lower() in ("it", "this", "that"):
            item = values.get("text", "")
        if not item:
            return []
        box = _innermost(item, "input[type=checkbox]")
        return [
            _step(n, "CLICK", f"the checkbox of '{item[:40]}'", target=box),
            _step(n + 1, "ASSERT_VISIBLE", f"'{item[:40]}' is ticked", target=f"{box}:checked"),
        ]

    m = re.match(r"^(?:open|go to|navigate to|visit|load)\s+(?:the\s+page\s+)?(/\S*|https?://\S+)$", p, re.IGNORECASE)
    if m:
        return [_step(n, "NAVIGATE", f"open {m.group(1)}", value=m.group(1))]

    m = re.match(r"^(?:click|press|tap|open|go to|navigate to|select|choose)\s+(?:on\s+)?(.+)$", p, re.IGNORECASE)
    if m or re.match(r"^(?:log ?out|sign ?out)$", p, re.IGNORECASE):
        # "click Sign in without filling anything": the label is what comes before the qualifier
        label = _noun(re.sub(r"\s+(?:without|before|after|while|instead)\b.*$", "", m.group(1), flags=re.IGNORECASE)) if m else p
        return [_step(n, "CLICK", f"'{label[:40]}'", target=f'{_ACTIONABLE}:has-text("{_quote(label)}")')] if label else []
    return []


def plan_goal(prompt: str | None, inputs: list[dict[str, Any]], values: dict[str, str],
              form_used: bool, first_step: int) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Outcome check for the form, steps for the later parts, and what was covered.

    Returns ``(steps, {"tested": [...], "untested": [...]})`` with steps
    numbered from *first_step*; no goal means no steps and empty lists.
    """
    parts = split_goal(prompt)
    tested: list[str] = []
    untested: list[str] = []
    steps: list[dict[str, Any]] = []
    n = first_step
    # "log in with a wrong password and check an error is shown": the goal expects the
    # form to be refused, so success is not asserted (its own checks say what to see)
    # Only the check right after the form speaks about it: in "log in, click Log out, check the
    # page does not show Signed in as" the check is about logging out, and the login must succeed
    refusal_expected = len(parts) > 1 and expects_failure(parts[1])
    for i, part in enumerate(parts):
        if i == 0 and form_used and (is_form_part(part, values) or not later_part_steps(n, part, values)):
            new = [] if refusal_expected else form_outcome(n, part, inputs, values)
            if refusal_expected:
                tested.append(part)
            elif new:
                tested.append(part)
            else:
                # Submitted, but nothing in the goal says what success looks like:
                # check the one thing true of every healthy app, and do not claim more
                new = [no_server_error(n)]
                untested.append(f"{part} (submitted; only checked that no server error appeared)")
        else:
            new = later_part_steps(n, part, values)
            (tested if new else untested).append(part)
        steps += new
        n += len(new)
    return steps, {"tested": tested, "untested": untested}
