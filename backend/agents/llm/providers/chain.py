"""
TestSphere-AI — Fallback chain of LLM providers (``LLM_PROVIDER=chain``).

Asks the providers of ``LLM_CHAIN`` in order (default: NVIDIA Gemma, NVIDIA
Nemotron, Groq, Gemini) and moves on when one cannot answer::

    LLM_PROVIDER=chain
    NVIDIA_API_KEY=nvapi-...        # or NVIDIA_GEMMA_API_KEY / NVIDIA_NEMOTRON_API_KEY
    GROQ_API_KEY=gsk_...
    GEMINI_API_KEY=...

A provider that fails is *benched* for a while, process-wide, so the rest of
the work (the remaining calls of a pipeline run, the next Test Studio draft)
goes straight to the next provider instead of hitting the same limit again:

    rate limit (429)      benched for the provider's Retry-After (60 s without one),
                          1 hour when its quota is used up (a daily or zero limit)
    bad key (401/403)     benched 1 hour, logged as a warning: check the key
    5xx, timeout, network benched 30 s
    other 4xx, bad answer not benched: the next provider answers this request

When every provider is benched they are all tried anyway, in order: a bench
is a guess about when a provider recovers, never a reason to give up.
Each answer carries the provider that gave it in ``LLMResponse.provider``.
"""

from __future__ import annotations

import logging
import threading
import time

from agents.llm.client import LLMClient
from agents.llm.config import ChainLink, LLMConfig, chain_links
from agents.llm.exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMConnectionError,
    LLMError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from agents.llm.schemas import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

RATE_LIMIT_BENCH_S = 60.0
QUOTA_BENCH_S = 3600.0
AUTH_BENCH_S = 3600.0
OUTAGE_BENCH_S = 30.0

# provider name -> monotonic time it may be asked again (shared by every client in the process)
_benched_until: dict[str, float] = {}
_lock = threading.Lock()


def bench(name: str, seconds: float) -> None:
    with _lock:
        _benched_until[name] = max(_benched_until.get(name, 0.0), time.monotonic() + seconds)


def benched_for(name: str) -> float:
    """Seconds until *name* is asked again (0 when it is available)."""
    with _lock:
        return max(0.0, _benched_until.get(name, 0.0) - time.monotonic())


def reset_benches() -> None:
    """Forget every bench (tests; an operator who fixed a key)."""
    with _lock:
        _benched_until.clear()


def bench_seconds(exc: LLMError) -> float:
    """How long a provider that raised *exc* is left out (0: only for this request)."""
    if isinstance(exc, LLMRateLimitError):
        if exc.quota_exhausted:
            return QUOTA_BENCH_S
        return max(exc.retry_after or RATE_LIMIT_BENCH_S, 1.0)
    if isinstance(exc, LLMAuthenticationError):
        return AUTH_BENCH_S
    if isinstance(exc, (LLMProviderError, LLMTimeoutError, LLMConnectionError)):
        return OUTAGE_BENCH_S
    return 0.0


class ChainProvider(LLMClient):
    """An ``LLMClient`` that answers with the first provider of the chain that can."""

    def __init__(self, config: LLMConfig, links: list[ChainLink] | None = None, *, transport=None) -> None:
        super().__init__(config)
        from agents.llm.providers.api import APIProvider

        links = chain_links() if links is None else links
        if not links:
            raise LLMConfigurationError("The LLM fallback chain has no provider with an API key.", provider="chain")
        self._links = [
            (link.name, APIProvider(
                LLMConfig(provider="api", api_key=link.api_key, model=link.model, base_url=link.base_url,
                          temperature=config.temperature, max_tokens=config.max_tokens, timeout=config.timeout,
                          max_retries=0),
                transport=transport, label=link.name, extra_body=dict(link.extra_body)))
            for link in links
        ]
        logger.info("LLM fallback chain: %s", " -> ".join(f"{link.name} ({link.model})" for link in links))

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self._links]

    async def generate(self, request: LLMRequest) -> LLMResponse:
        ready = [(n, p) for n, p in self._links if benched_for(n) == 0]
        order = ready or self._links  # all benched: try them anyway
        failures: list[tuple[str, LLMError]] = []
        for name, provider in order:
            try:
                response = await provider.generate(request)
            except LLMError as exc:
                seconds = bench_seconds(exc)
                if seconds:
                    bench(name, seconds)
                level = logging.WARNING if isinstance(exc, LLMAuthenticationError) else logging.INFO
                logger.log(level, "LLM provider %s failed (%s: %s)%s; trying the next one", name,
                           type(exc).__name__, str(exc)[:200], f", benched {seconds:.0f}s" if seconds else "")
                failures.append((name, exc))
                continue
            if failures:
                logger.info("LLM chain: %s answered after %s failed", name, ", ".join(n for n, _ in failures))
            return response
        raise self._all_failed(failures)

    @staticmethod
    def _all_failed(failures: list[tuple[str, LLMError]]) -> LLMError:
        summary = "; ".join(f"{name}: {type(exc).__name__}" for name, exc in failures)
        message = f"Every LLM provider in the chain failed ({summary})."
        if failures and all(isinstance(exc, LLMRateLimitError) for _, exc in failures):
            # The session may wait for the soonest one and try again
            waits = [exc.retry_after for _, exc in failures if exc.retry_after]
            return LLMRateLimitError(message, provider="chain", retry_after=min(waits) if waits else None,
                                     quota_exhausted=all(exc.quota_exhausted for _, exc in failures))
        if failures and all(isinstance(exc, LLMAuthenticationError) for _, exc in failures):
            return LLMAuthenticationError(message, provider="chain")
        return LLMProviderError(message, provider="chain")
