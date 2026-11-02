"""Token budget: charged per call, enforced before each call, shared across tasks and threads."""

import asyncio

import pytest

from agents.llm.budget import TokenBudget, current_budget, token_budget
from agents.llm.client import LLMClient, LLMClientSession
from agents.llm.config import LLMConfig
from agents.llm.exceptions import LLMBudgetExceededError
from agents.llm.schemas import LLMRequest, LLMResponse, LLMUsage


class Counting(LLMClient):
    """A real-looking provider: every answer costs 600 + 400 tokens."""

    def __init__(self, provider="api", model="llama-3.3-70b-versatile"):
        super().__init__(LLMConfig(provider=provider, api_key="k", model=model, max_retries=0))
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        return LLMResponse(content="ok", model=self.config.model, provider=self.config.provider,
                           usage=LLMUsage(prompt_tokens=600, completion_tokens=400))


def ask(session):
    return asyncio.run(session.generate(LLMRequest(prompt="hi")))


def test_calls_are_charged_and_refused_once_the_budget_is_used_up():
    provider = Counting()
    session = LLMClientSession(provider)
    with token_budget(2000) as budget:
        ask(session)
        ask(session)  # 2000 used: the limit is reached, not passed
        with pytest.raises(LLMBudgetExceededError) as exc:
            ask(session)
    assert provider.calls == 2 and not exc.value.is_retryable
    assert budget.summary() == {"calls": 2, "input_tokens": 1200, "output_tokens": 800, "limit": 2000,
                                "budget_exhausted": True}
    assert current_budget() is None  # the block is over
    ask(session)  # no budget outside it


def test_no_limit_still_counts():
    with token_budget(0) as budget:
        for _ in range(5):
            ask(LLMClientSession(Counting(model="some-local-model")))
    assert budget.used == 5000 and not budget.exhausted


def test_the_mock_provider_is_never_charged_or_refused():
    with token_budget(1) as budget:
        ask(LLMClientSession(Counting(provider="mock")))
        ask(LLMClientSession(Counting(provider="mock")))
    assert budget.calls == 0


def test_calls_in_threads_and_tasks_charge_the_same_budget():
    session = LLMClientSession(Counting())

    async def everywhere():
        await asyncio.gather(session.generate(LLMRequest(prompt="a")), session.generate(LLMRequest(prompt="b")))
        await asyncio.to_thread(ask, session)  # a thread with its own event loop

    with token_budget(0) as budget:
        asyncio.run(everywhere())
    assert budget.calls == 3


def test_a_budget_starts_empty():
    assert TokenBudget(10).summary()["calls"] == 0 and not TokenBudget(0).exhausted
