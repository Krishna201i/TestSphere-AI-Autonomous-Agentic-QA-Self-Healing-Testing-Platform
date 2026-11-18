"""
Selectors the page analyzer writes into generated tests.

They used to be built by hand: ``input:nth-of-type(N)`` counted every input of
the page (CSS counts siblings, so it pointed at the wrong field or none),
``button.<first class>`` matched every button sharing a class like ``btn``,
and ids and attribute values were pasted in unescaped (React's ``:r1:`` gave
the invalid ``#:r1:``).  Now each selector is the first stable candidate
(data-testid, id, name, aria-label, placeholder, type, text) that matches
exactly one element of the page, escaped; a field with none is left out.
"""

from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from backend.services.url_analyzer import URLAnalyzerService as U
from engine.locators import (
    best_unique,
    css_string,
    id_selector,
    stable_candidates,
    xpath_string,
)

TRICKY = """<html><body>
<header><form action="/search"><input type="search" placeholder="Search docs">
<button class="btn btn-sm">Search</button></form></header>
<main><form action="/login" method="post">
<input id=":r1:" name="email" type="email">
<input name="password" type="password" aria-label="Don't share this">
<input type="text">
<input type="text">
<label><input type="radio" name="plan" value="free"> Free</label>
<label><input type="radio" name="plan" value="pro"> Pro</label>
<input data-testid="remember &amp; me" type="checkbox">
<button class="btn hover:bg-blue-500" type="submit">Sign in</button>
<button class="btn" type="button">Sign in with Google</button>
<input type="submit" value='Say "hi"'>
</form></main></body></html>"""


def test_no_selector_uses_position_or_a_class():
    selectors = [i["selector"] for i in U._extract_inputs(TRICKY)] + [b["selector"] for b in U._extract_buttons(TRICKY)]
    assert not any("nth-of-type" in s or ".btn" in s or s.startswith("button.") for s in selectors), selectors


def test_unidentifiable_fields_are_left_out_not_guessed():
    inputs = U._extract_inputs(TRICKY)
    # The two bare <input type="text"> have nothing that tells them apart
    assert not any(i["type"] == "text" for i in inputs)
    assert {i["selector"] for i in inputs if i["type"] == "radio"} == {
        'input[name="plan"][value="free"]', 'input[name="plan"][value="pro"]'}


def test_attribute_values_are_decoded_and_escaped():
    inputs = {i["type"]: i for i in U._extract_inputs(TRICKY)}
    assert inputs["email"]["selector"] == '[id=":r1:"]'
    assert inputs["password"]["selector"] == 'input[name="password"]'
    assert inputs["password"]["aria_label"] == "Don't share this"  # a quote of the other kind no longer cuts it
    assert inputs["checkbox"]["selector"] == '[data-testid="remember & me"]'


def test_buttons_get_exact_text_when_a_longer_label_contains_theirs():
    buttons = {b["text"]: b["selector"] for b in U._extract_buttons(TRICKY)}
    assert buttons["Sign in"] == 'button:text-is("Sign in")'
    assert buttons["Sign in with Google"] == 'button:has-text("Sign in with Google")'
    assert buttons['Say "hi"'] == 'input[value="Say \\"hi\\""]'


def test_a_button_without_a_type_submits_its_form():
    (button,) = U._extract_buttons("<form><button>Go</button></form>")
    assert button["type"] == "submit"


async def test_every_selector_matches_exactly_its_element_in_a_real_browser():
    elements = U._extract_inputs(TRICKY) + U._extract_buttons(TRICKY)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(TRICKY)
        for element in elements:
            assert await page.locator(element["selector"]).count() == 1, element
        await browser.close()


@pytest.mark.parametrize(("value", "expected"), [
    ("plain", '"plain"'), ('say "hi"', '"say \\"hi\\""'), ("back\\slash", '"back\\\\slash"'),
])
def test_css_strings_are_escaped(value, expected):
    assert css_string(value) == expected


def test_ids_that_are_not_plain_identifiers_use_an_attribute_selector():
    assert id_selector("email") == "#email"
    assert id_selector(":r1:") == '[id=":r1:"]'
    assert id_selector("1st") == '[id="1st"]'
    assert id_selector("a.b") == '[id="a.b"]'


def test_xpath_strings_survive_both_kinds_of_quote():
    assert xpath_string("plain") == '"plain"'
    assert xpath_string('say "hi"') == "'say \"hi\"'"
    assert xpath_string("it's \"x\"") == 'concat("it\'s ", \'"\', "x", \'"\', "")'


def test_best_unique_skips_candidates_shared_with_other_elements():
    page = [("button", {"class": "btn", "type": "submit"}, "Save"), ("button", {"class": "btn"}, "Save draft")]
    assert best_unique(stable_candidates("button", page[0][1], "Save"), page) == 'button:text-is("Save")'
    assert best_unique(stable_candidates("button", {}, None), page) is None


def test_a_type_less_toggle_is_not_pressed_instead_of_sign_in():
    page = """<form><input id="email" type="email"><input id="pw" type="password">
    <button aria-label="Show password">👁</button><button type="submit">Sign in</button></form>"""
    inputs, buttons = U._extract_inputs(page), U._extract_buttons(page)
    assert U._primary_button(buttons, bool(inputs))["text"] == "Sign in"


def test_a_form_whose_only_button_has_no_type_still_submits_with_it():
    page = '<form><input id="q" name="q"><button class="go">Find</button></form>'
    inputs, buttons = U._extract_inputs(page), U._extract_buttons(page)
    assert U._primary_button(buttons, bool(inputs))["text"] == "Find"


# ── Every submit checks something; coverage is not over-claimed ──

CONTACT = """<form action="/contact" method="post"><input id="name" name="name" required>
<textarea id="msg" name="message" required></textarea><button type="submit">Send</button></form>"""


def _scenario(prompt=None):
    return U._plan_scenario("https://app.example/contact", "Contact", U._extract_inputs(CONTACT),
                            U._extract_buttons(CONTACT), prompt)


def test_a_submit_without_a_goal_still_checks_for_a_server_error():
    steps, _ = _scenario()
    actions = [s["action"] for s in steps]
    assert actions.index("CLICK") < len(actions) - 1, "the test must not end on the click"
    assert steps[-1]["action"] == "ASSERT_HIDDEN" and "server error" in steps[-1]["description"]


def test_a_goal_without_a_checkable_outcome_is_not_reported_as_tested():
    steps, coverage = _scenario("submit the contact form")
    assert coverage["tested"] == []
    assert coverage["untested"] == ["submit the contact form (submitted; only checked that no server error appeared)"]
    assert steps[-1]["description"] == "no server error is shown"
