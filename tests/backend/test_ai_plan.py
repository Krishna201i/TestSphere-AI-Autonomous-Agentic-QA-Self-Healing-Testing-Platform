"""The LLM Test Planner in the pipeline: kept only when every element exists; quarantined; never fails a run."""

import asyncio

from agents.planner.schemas import Assertion, TestCase, TestPlan, TestStep
from agents.schemas.enums import AssertionType, TestAction
from backend.config import settings
from backend.models import TEST_CASES
from backend.pipeline import ai_plan, runner
from backend.services.project_service import ProjectService

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
    assert "dropped 1 that used elements not on the page" in note
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
    async def fake_ai(analysis, prompt, frameworks=None):
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
    changed = case("TC_LOGIN", [(TestAction.FILL, "#user", "bob"), (TestAction.CLICK, "#go", None)])

    async def changed_ai(analysis, prompt, frameworks=None):
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
