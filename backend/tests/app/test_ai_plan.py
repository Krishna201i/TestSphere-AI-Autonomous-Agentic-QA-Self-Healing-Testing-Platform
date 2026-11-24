"""The LLM Test Planner in the pipeline: kept only when every element exists; quarantined; never fails a run."""

import asyncio

from agents.planner.schemas import Assertion, TestCase, TestPlan, TestStep
from agents.schemas.enums import AssertionType, TestAction
from app.config import settings
from app.models import TEST_CASES
from app.pipeline import ai_plan, runner
from app.services.project_service import ProjectService

URL = "http://app.test/login"
ANALYSIS = {
    "url": URL, "page_title": "Shop Login", "status_code": 200, "latency_ms": 5,
    "elements_inventory": {
        "inputs": [{"selector": "#user", "type": "text", "name": "user", "id": "user"},
                   {"selector": "#pass", "type": "password", "name": "pass", "id": "pass"}],
        "buttons": [{"selector": "#go", "text": "Log in", "type": "submit", "id": "go"}, {"selector": "button", "text": ""}],
        "links": ["/about"],
    },
    "synthesized_test_case": {"steps": []},
}


def case(test_id, steps, assertions=()):
    return TestCase(test_id=test_id, name=test_id.replace("_", " "), steps=[
        TestStep(step_number=i, action=a, target=t, value=v) for i, (a, t, v) in enumerate(steps, start=1)],
        assertions=list(assertions))


class FakePlanner:
    def __init__(self, cases=None, error=None, delay=0.0):
        self.cases, self.error, self.delay, self.context = cases or [], error, delay, None

    async def generate_test_plan(self, context, max_tests=10, prioritize=False):
        self.context = context
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return TestPlan(application_name="Shop", base_url=URL, generated_at="now", test_cases=self.cases)


LOGIN = case("TC_LOGIN", [(TestAction.NAVIGATE, None, URL), (TestAction.FILL, "#user", "ann"),
                          (TestAction.FILL, "#pass", "pw"), (TestAction.CLICK, "#go", None)],
             [Assertion(type=AssertionType.URL_CONTAINS, expected="/account", description="lands on the account")])
INVENTED = case("TC_GHOST", [(TestAction.CLICK, "#forgot-password", None)])


def test_planner_tests_use_only_elements_found_on_the_page():
    planner = FakePlanner([LOGIN, INVENTED])
    tests, note = asyncio.run(ai_plan.ai_tests(ANALYSIS, "log in as ann", planner=planner))
    assert [t["name"] for t in tests] == ["AI: TC LOGIN"]
    assert [s["action"] for s in tests[0]["steps"]] == ["NAVIGATE", "FILL", "FILL", "CLICK", "ASSERT_URL"]
    assert tests[0]["steps"][-1]["value"] == "/account" and tests[0]["category"] == "ai"
    assert "dropped 1 that used elements not on their page" in note
    # the planner saw the page's real elements and the goal (never the bare "button")
    assert {e.selector for e in planner.context.pages[0].elements} == {"#user", "#pass", "#go"}
    assert "log in as ann" in planner.context.description


def test_a_failing_or_slow_planner_leaves_the_rule_based_suite_alone():
    tests, note = asyncio.run(ai_plan.ai_tests(ANALYSIS, None, planner=FakePlanner(error=RuntimeError("model down"))))
    assert tests == [] and "AI planner skipped (RuntimeError: model down)" in note
    tests, note = asyncio.run(ai_plan.ai_tests(ANALYSIS, None, planner=FakePlanner([LOGIN], delay=1), timeout=0.05))
    assert tests == [] and "TimeoutError" in note


def test_off_with_the_mock_model(monkeypatch):
    monkeypatch.setattr(settings, "PIPELINE_AI_PLANNER", "auto")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    assert ai_plan.enabled() is False
    assert asyncio.run(ai_plan.ai_tests(ANALYSIS, None)) == ([], None)
    monkeypatch.setattr(settings, "PIPELINE_AI_PLANNER", "on")
    assert ai_plan.enabled() is True


def test_the_plan_stage_quarantines_ai_tests(fresh_store, monkeypatch):
    async def fake_ai(analysis, prompt, frameworks=None, **_):
        return ai_plan.to_suite_tests([LOGIN], analysis)[0], "AI planner added 1 test(s)"

    monkeypatch.setattr(ai_plan, "ai_tests", fake_ai)
    project = ProjectService.create_project(fresh_store, name="Shop", owner_uid="local-dev", app_url=URL)
    _, cases, detail = asyncio.run(runner._plan(fresh_store, project, ANALYSIS, None))
    ai = [c for c in cases if c["category"] == "ai"]
    assert len(ai) == 1 and ai[0]["quarantined"] is True
    assert "AI planner added 1 test(s)" in detail
    # a person un-quarantines it; the next plan keeps that decision
    fresh_store.update(TEST_CASES, ai[0]["id"], quarantined=False)
    _, cases, _ = asyncio.run(runner._plan(fresh_store, project, ANALYSIS, None))
    assert [c["quarantined"] for c in cases if c["category"] == "ai"] == [False]
    # the model reuses the id for different steps: that test was never reviewed
    changed = case("TC_LOGIN", [(TestAction.FILL, "#user", "bob"), (TestAction.CLICK, "#go", None)],
                   [Assertion(type=AssertionType.URL_CONTAINS, expected="/account")])

    async def changed_ai(analysis, prompt, frameworks=None, **_):
        return ai_plan.to_suite_tests([changed], analysis)[0], "AI planner added 1 test(s)"

    monkeypatch.setattr(ai_plan, "ai_tests", changed_ai)
    _, cases, _ = asyncio.run(runner._plan(fresh_store, project, ANALYSIS, None))
    assert [c["quarantined"] for c in cases if c["category"] == "ai"] == [True]


def test_checks_and_exact_assertions_are_kept_not_dropped():
    terms = {**ANALYSIS, "elements_inventory": {**ANALYSIS["elements_inventory"], "inputs": [
        *ANALYSIS["elements_inventory"]["inputs"], {"selector": "#terms", "type": "checkbox", "id": "terms"}]}}
    signup = case("TC_SIGNUP", [(TestAction.FILL, "#user", "ann"), (TestAction.CHECK, "#terms", None),
                                (TestAction.CLICK, "#go", None)],
                  [Assertion(type=AssertionType.VALUE_EQUALS, target="#user", expected="ann"),
                   Assertion(type=AssertionType.ELEMENT_HAS_TEXT, target="#go", expected="Log in"),
                   Assertion(type=AssertionType.URL_EQUALS, expected="http://app.test/account")])
    tests, dropped = ai_plan.to_suite_tests([signup], terms)
    assert dropped == 0
    assert [s["action"] for s in tests[0]["steps"]] == [
        "NAVIGATE", "FILL", "CHECK", "CLICK", "ASSERT_VALUE", "ASSERT_HAS_TEXT", "ASSERT_URL_EQUALS"]


def test_the_mock_planner_answers_with_its_scenarios(monkeypatch):
    monkeypatch.setattr(settings, "PIPELINE_AI_PLANNER", "on")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    tests, note = asyncio.run(ai_plan.ai_tests(ANALYSIS, "log in"))
    assert "skipped" not in (note or ""), note


def test_an_ai_test_is_identified_by_its_steps_not_the_models_id():
    """The model's test ids change between runs (a new row each time) and get reused
    for other steps (overwriting a test someone had trusted)."""
    renamed = case("TC_LOGIN_RENAMED", [(TestAction.NAVIGATE, None, URL), (TestAction.FILL, "#user", "ann"),
                                        (TestAction.FILL, "#pass", "pw"), (TestAction.CLICK, "#go", None)],
                   LOGIN.assertions)
    reused = case("TC_LOGIN", [(TestAction.NAVIGATE, None, URL), (TestAction.CLICK, "#go", None)],
                  [Assertion(type=AssertionType.URL_CONTAINS, expected="/account")])
    first, _ = asyncio.run(ai_plan.ai_tests(ANALYSIS, "log in", planner=FakePlanner([LOGIN])))
    again, _ = asyncio.run(ai_plan.ai_tests(ANALYSIS, "log in", planner=FakePlanner([renamed])))
    other, _ = asyncio.run(ai_plan.ai_tests(ANALYSIS, "log in", planner=FakePlanner([reused])))
    assert first[0]["slug"] == again[0]["slug"]   # same steps, new id: same test
    assert other[0]["slug"] != first[0]["slug"]   # same id, other steps: another test


def test_a_test_that_checks_nothing_a_broken_page_would_fail_is_dropped():
    body_only = case("TC_BODY", [(TestAction.FILL, "#user", "ann"), (TestAction.CLICK, "#go", None)],
                     [Assertion(type=AssertionType.ELEMENT_VISIBLE, target="body")])
    check_before_click = case("TC_EARLY", [(TestAction.FILL, "#user", "ann"), (TestAction.CLICK, "#go", None)],
                              [])
    check_before_click.steps[0].assertions.append(
        Assertion(type=AssertionType.VALUE_EQUALS, target="#user", expected="ann"))
    tests, dropped = ai_plan.to_suite_tests([body_only, check_before_click, LOGIN], ANALYSIS)
    assert dropped == 2 and [t["name"] for t in tests] == ["AI: TC LOGIN"]


ABOUT = "http://app.test/about"
ABOUT_PAGE = {"url": ABOUT, "page_title": "About us", "elements_inventory": {
    "inputs": [{"selector": "#email", "type": "email", "name": "email"}],
    "buttons": [{"selector": "#subscribe", "text": "Subscribe"}], "headings": ["Our team"]}}


def test_a_journey_may_move_to_another_analyzed_page_and_use_its_elements():
    journey = case("TC_NEWSLETTER", [(TestAction.NAVIGATE, None, "/about"), (TestAction.FILL, "#email", "a@b.test"),
                                     (TestAction.CLICK, "#subscribe", None)],
                   [Assertion(type=AssertionType.ELEMENT_CONTAINS_TEXT, target="body", expected="Thanks")])
    tests, dropped = ai_plan.to_suite_tests([journey], ANALYSIS, {ABOUT: ABOUT_PAGE})
    assert dropped == 0
    assert [(s["action"], s["value"]) for s in tests[0]["steps"][:2]] == [("NAVIGATE", URL), ("NAVIGATE", ABOUT)]
    # without that page's analysis its elements are guesses
    assert ai_plan.to_suite_tests([journey], ANALYSIS)[1] == 1
    # an element from the start page is not on /about
    wrong_page = case("TC_WRONG", [(TestAction.NAVIGATE, None, "/about"), (TestAction.CLICK, "#go", None)],
                      [Assertion(type=AssertionType.URL_CONTAINS, expected="/x")])
    assert ai_plan.to_suite_tests([wrong_page], ANALYSIS, {ABOUT: ABOUT_PAGE})[1] == 1


def test_the_planner_sees_every_analyzed_page():
    planner = FakePlanner([LOGIN])
    asyncio.run(ai_plan.ai_tests(ANALYSIS, None, planner=planner, pages={ABOUT: ABOUT_PAGE}))
    assert [p.url for p in planner.context.pages] == ["/login", "/about"]
    assert "Our team" in planner.context.pages[1].description
