"""
Check every provider of the LLM fallback chain with one tiny request::

    cd backend && python -m agents.llm.check

Prints, per provider in ``LLM_CHAIN`` order, whether its key is set and
whether it answered (with the model and time), so a wrong key, a model name
the provider does not serve, or a used-up quota shows up before a pipeline
run relies on it.  Keys are never printed.  Exit code 1 if none answered.
"""

from __future__ import annotations

import asyncio
import sys
import time

from agents.llm.config import LLMConfig, chain_links
from agents.llm.providers.api import APIProvider
from agents.llm.schemas import LLMRequest


async def check() -> int:
    base = LLMConfig.from_env()  # loads .env
    print(f"LLM_PROVIDER={base.provider}")
    ok = 0
    for link in chain_links(configured_only=False):
        if not link.api_key:
            print(f"  {link.name:16} {link.model:42} skipped: no API key set")
            continue
        provider = APIProvider(LLMConfig(provider="api", api_key=link.api_key, model=link.model, base_url=link.base_url,
                                         max_tokens=20, timeout=base.timeout, max_retries=0),
                               label=link.name, extra_body=dict(link.extra_body))
        started = time.monotonic()
        try:
            answer = await provider.generate(LLMRequest(prompt="Reply with the single word: ok", temperature=0.0,
                                                        max_tokens=20))
        except Exception as exc:  # noqa: BLE001 - reported, the next provider is still checked
            print(f"  {link.name:16} {link.model:42} FAILED: {type(exc).__name__}: {str(exc)[:160]}")
            continue
        ok += 1
        print(f"  {link.name:16} {link.model:42} ok in {time.monotonic() - started:.1f}s: {answer.content.strip()[:30]!r}")
    print(f"{ok} provider(s) answered.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(check()))
