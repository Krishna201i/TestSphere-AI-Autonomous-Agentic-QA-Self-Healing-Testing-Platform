"""
TestSphere-AI — LLM token budget

A budget caps the tokens every LLM call made inside a ``with token_budget(n)``
block may use together (e.g. one pipeline run).  It lives in a context
variable, so calls in tasks and threads started inside the block charge the
same budget without it being passed around.

``LLMClientSession.generate`` refuses a call once the budget is used up
(``LLMBudgetExceededError``, not retried); the check is made before each
call, so the last one can go over by at most its own response.

Usage::

    with token_budget(300_000) as budget:
        await run_the_pipeline()
    run["llm_usage"] = budget.summary()
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from contextvars import ContextVar

from agents.llm.schemas import LLMUsage


class TokenBudget:
    """Tokens used so far against a limit (0 = no limit, usage still counted)."""

    def __init__(self, limit: int) -> None:
        self.limit = max(0, int(limit))
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._lock = threading.Lock()

    @property
    def used(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def exhausted(self) -> bool:
        return bool(self.limit) and self.used >= self.limit

    def charge(self, usage: LLMUsage) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += usage.prompt_tokens
            self.output_tokens += usage.completion_tokens

    def summary(self) -> dict[str, int | bool | None]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "limit": self.limit or None,
            "budget_exhausted": self.exhausted,
        }


_current: ContextVar[TokenBudget | None] = ContextVar("llm_token_budget", default=None)


def current_budget() -> TokenBudget | None:
    """The budget the calling code runs under, if any."""
    return _current.get()


@contextlib.contextmanager
def token_budget(limit: int) -> Iterator[TokenBudget]:
    """Charge every LLM call inside the block to one new budget."""
    budget = TokenBudget(limit)
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)
