"""
Planner output that real models produce and that must not lose the plan:

- one test case outside the vocabulary (an action like "type") or with a
  lowercase priority: only that case is dropped / the field normalized;
- JSON wrapped in a markdown code fence, or surrounded by prose.
"""

import copy
import json

import pytest

from agents.llm.client import LLMClientSession
from agents.llm.config import LLMConfig
from agents.llm.exceptions import LLMResponseError
from agents.llm.parser import loads_json_object
from agents.llm.providers.mock import MockLLMProvider
from agents.llm.schemas import LLMRequest
from agents.planner.mock_scenarios import VALID_TEST_PLAN_RESPONSE
from agents.planner.planner import LLMTestPlanner
from agents.planner.validation import TestPlanValidationError

PLAN = json.loads(VALID_TEST_PLAN_RESPONSE)


def _plan_with_bad_second_case() -> dict:
    data = copy.deepcopy(PLAN)
    good = data["test_cases"][0]
    bad = copy.deepcopy(good)
    bad["test_id"] = "TC_BAD"
    bad["steps"][0]["action"] = "type"
    good["priority"] = good["priority"].lower()
    data["test_cases"] = [good, bad]
    return data


def test_one_unparseable_case_is_dropped_not_the_plan():
    plan = LLMTestPlanner._parse_response(_plan_with_bad_second_case())
    assert [tc.test_id for tc in plan.test_cases] == [PLAN["test_cases"][0]["test_id"]]
    assert plan.test_cases[0].priority.value == PLAN["test_cases"][0]["priority"].upper()


def test_a_plan_with_no_parseable_case_is_rejected():
    data = _plan_with_bad_second_case()
    data["test_cases"] = data["test_cases"][1:]
    with pytest.raises(TestPlanValidationError, match="None of the 1 test case"):
        LLMTestPlanner._parse_response(data)


@pytest.mark.parametrize("wrapped", [
    f"```json\n{VALID_TEST_PLAN_RESPONSE}\n```",
    f"```\n{VALID_TEST_PLAN_RESPONSE}\n```",
    f"Here is the plan:\n\n```json\n{VALID_TEST_PLAN_RESPONSE}\n```\nLet me know!",
    f"Sure. {VALID_TEST_PLAN_RESPONSE} Hope this helps.",
])
async def test_generate_json_reads_fenced_or_wrapped_json(wrapped):
    provider = MockLLMProvider(LLMConfig(provider="mock", model="mock-model"))
    provider.register_response("plan", wrapped)
    session = LLMClientSession(provider, LLMConfig(provider="mock", model="mock-model"))

    data = await session.generate_json(LLMRequest(prompt="plan please"))

    assert data == PLAN


async def test_generate_json_still_rejects_text_without_json():
    provider = MockLLMProvider(LLMConfig(provider="mock", model="mock-model"))
    provider.register_response("plan", "I cannot help with that.")
    session = LLMClientSession(provider, LLMConfig(provider="mock", model="mock-model"))
    with pytest.raises(LLMResponseError, match="not valid JSON"):
        await session.generate_json(LLMRequest(prompt="plan please"))


def test_loads_json_object_prefers_the_plain_parse():
    assert loads_json_object('{"a": "```"}') == {"a": "```"}
