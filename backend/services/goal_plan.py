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

# Parts of a goal: split on "and"/"then"/commas, but "username X and password Y" stays one part
_SPLIT = re.compile(r"\s*(?:,\s*(?:and\s+|then\s+)?|;\s*|\s+and then\s+|\s+then\s+|\s+and\s+)", re.IGNORECASE)
_FORM_VERB = re.compile(r"^(?:log ?in|sign ?in|search|type|enter|fill|submit)\b", re.IGNORECASE)
_CREDENTIAL = re.compile(r"^(?:(?:the|my|a)\s+)?(?:pass(?:word)?|user ?name|user|e-?mail|login)\b", re.IGNORECASE)
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
        return [_step(n, "ASSERT_HIDDEN", "the sign-in form (it should be gone after signing in)",
                      target=password["selector"])]
    text = values.get("text")
    if text and re.match(r"^(?:add|create|post|write)\b", part, re.IGNORECASE):
        return [_step(n, "ASSERT_CONTAINS_TEXT", f"the new item '{text[:40]}' shows on the page",
                      target="body", value=text)]
    return []


def later_part_steps(n: int, part: str, values: dict[str, str]) -> list[dict[str, Any]]:
    """Steps for one part after the form; [] when it cannot be turned into steps."""
    p = part.strip()
    if re.match(r"^(?:check|verify|confirm|see)\b.*\b(?:loads?|opens?|works?|renders?)$", p, re.IGNORECASE):
        return [_step(n, "ASSERT_VISIBLE", "the page loads", target="body")]
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

    m = re.match(r"^(?:click|press|tap|open|go to|navigate to|select|choose)\s+(?:on\s+)?(.+)$", p, re.IGNORECASE)
    if m or re.match(r"^(?:log ?out|sign ?out)$", p, re.IGNORECASE):
        label = _noun(m.group(1)) if m else p
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
    for i, part in enumerate(parts):
        if i == 0 and form_used and (is_form_part(part, values) or not later_part_steps(n, part, values)):
            tested.append(part)
            new = form_outcome(n, part, inputs, values)
        else:
            new = later_part_steps(n, part, values)
            (tested if new else untested).append(part)
        steps += new
        n += len(new)
    return steps, {"tested": tested, "untested": untested}
