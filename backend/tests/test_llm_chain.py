"""
The LLM fallback chain (LLM_PROVIDER=chain): NVIDIA Gemma -> Nemotron -> Groq -> Gemini.

HTTP is stubbed with httpx.MockTransport: no network, no real keys.
"""

from __future__ import annotations

import json

import httpx
import pytest

from agents.llm.client import LLMClientSession
from agents.llm.config import NVIDIA_BASE_URL, ChainLink, LLMConfig, chain_links
from agents.llm.exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProviderError,
    LLMRateLimitError,
)
from agents.llm.factory import get_llm_provider
from agents.llm.providers import chain as chain_mod
from agents.llm.providers.chain import ChainProvider, benched_for
from agents.llm.schemas import LLMRequest

CHAIN_ENV = ("LLM_CHAIN", "NVIDIA_API_KEY", "NVIDIA_GEMMA_API_KEY", "NVIDIA_NEMOTRON_API_KEY", "GROQ_API_KEY",
             "GEMINI_API_KEY", "NVIDIA_NEMOTRON_THINKING", "GEMINI_MODEL")

LINKS = [
    ChainLink("nvidia-gemma", "https://nvidia.test/v1", "google/gemma-4-31b-it", "k1"),
    ChainLink("nvidia-nemotron", "https://nvidia.test/v1", "nvidia/nemotron-3-ultra-550b-a55b", "k2",
              (("chat_template_kwargs", {"enable_thinking": False}),)),
    ChainLink("groq", "https://groq.test/v1", "openai/gpt-oss-120b", "k3"),
    ChainLink("gemini", "https://gemini.test/v1", "gemini-3.8-flash", "k4"),
]


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in CHAIN_ENV:
        monkeypatch.delenv(name, raising=False)
    chain_mod.reset_benches()
    yield
    chain_mod.reset_benches()


def completion(text: str) -> dict:
    return {"model": "m", "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2}}


class Network:
    """Answers per model: a list of (status, body) consumed in order, the last one repeated."""

    def __init__(self, **plans):
        self.plans = {model: list(steps) for model, steps in plans.items()}
        self.calls: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append({"model": body["model"], "body": body, "auth": request.headers.get("authorization")})
        steps = self.plans.get(body["model"]) or [(200, completion(f"from {body['model']}"))]
        status, payload = steps.pop(0) if len(steps) > 1 else steps[0]
        return httpx.Response(status, json=payload, headers=payload.pop("_headers", {}) if isinstance(payload, dict) else {})

    def models(self) -> list[str]:
        return [c["model"] for c in self.calls]


def make(network: Network, links=LINKS) -> ChainProvider:
    return ChainProvider(LLMConfig(provider="chain", model="chain", max_retries=0), links,
                         transport=httpx.MockTransport(network))


REQ = LLMRequest(prompt="hi")
GEMMA, NEMOTRON, GROQ, GEMINI = (link.model for link in LINKS)


def limited(retry_after=None, daily=False):
    error = {"message": "Rate limit reached" + (" (limit: 0)" if daily else "")}
    body = {"error": error}
    if retry_after:
        body["_headers"] = {"retry-after": str(retry_after)}
    return (429, body)


# ---------------------------------------------------------------------------
# Order and failover
# ---------------------------------------------------------------------------


async def test_gemma_answers_first():
    net = Network()
    answer = await make(net).generate(REQ)
    assert net.models() == [GEMMA]
    assert answer.content == f"from {GEMMA}" and answer.provider == "nvidia-gemma"


async def test_a_rate_limited_gemma_hands_the_request_to_nemotron():
    net = Network(**{GEMMA: [limited(retry_after=45)]})
    answer = await make(net).generate(REQ)
    assert net.models() == [GEMMA, NEMOTRON]
    assert answer.provider == "nvidia-nemotron"
    assert 40 < benched_for("nvidia-gemma") <= 45


async def test_the_rest_of_the_work_continues_on_nemotron_without_retrying_gemma():
    net = Network(**{GEMMA: [limited()]})
    chain = make(net)
    for _ in range(3):  # e.g. the remaining calls of a pipeline run
        assert (await chain.generate(REQ)).provider == "nvidia-nemotron"
    assert net.models() == [GEMMA, NEMOTRON, NEMOTRON, NEMOTRON]


async def test_the_bench_is_shared_by_every_client_in_the_process():
    net = Network(**{GEMMA: [limited()]})
    await make(net).generate(REQ)
    await make(net).generate(REQ)  # a new client (a new Test Studio draft) skips Gemma too
    assert net.models() == [GEMMA, NEMOTRON, NEMOTRON]


async def test_down_the_whole_chain_to_gemini():
    net = Network(**{GEMMA: [limited(daily=True)], NEMOTRON: [(503, {"error": "overloaded"})],
                     GROQ: [limited(retry_after=10)]})
    answer = await make(net).generate(REQ)
    assert net.models() == [GEMMA, NEMOTRON, GROQ, GEMINI]
    assert answer.provider == "gemini"
    assert benched_for("nvidia-gemma") > 3000  # the daily quota: out for an hour
    assert 0 < benched_for("nvidia-nemotron") <= 30  # an outage: briefly
    assert 0 < benched_for("groq") <= 10


async def test_gemma_is_first_again_once_its_bench_ends(monkeypatch):
    net = Network(**{GEMMA: [limited(retry_after=5), (200, completion("gemma is back"))]})
    chain = make(net)
    await chain.generate(REQ)
    clock = chain_mod.time.monotonic() + 6
    monkeypatch.setattr(chain_mod.time, "monotonic", lambda: clock)
    assert (await chain.generate(REQ)).content == "gemma is back"


async def test_a_bad_key_is_benched_and_logged(caplog):
    net = Network(**{GEMMA: [(401, {"error": {"message": "invalid api key"}})]})
    with caplog.at_level("WARNING"):
        answer = await make(net).generate(REQ)
    assert answer.provider == "nvidia-nemotron"
    assert benched_for("nvidia-gemma") > 3000
    assert any("nvidia-gemma" in r.message and "LLMAuthenticationError" in r.message for r in caplog.records)


async def test_a_bad_answer_moves_on_without_benching():
    net = Network(**{GEMMA: [(200, {"choices": []})]})
    answer = await make(net).generate(REQ)
    assert answer.provider == "nvidia-nemotron" and benched_for("nvidia-gemma") == 0


async def test_when_everything_is_benched_all_are_tried_anyway():
    net = Network(**{GEMMA: [limited(), (200, completion("ok"))]})
    for link in LINKS[1:]:
        chain_mod.bench(link.name, 999)
    chain = make(net)
    with pytest.raises(LLMRateLimitError):  # gemma limited, the rest benched: nothing ready, gemma fails
        await chain.generate(REQ)
    # Every provider is benched now; the next request still tries them in order
    answer = await chain.generate(REQ)
    assert answer.content == "ok"


async def test_every_provider_failing_says_which_failed_how():
    net = Network(**{m: [(500, {"error": "down"})] for m in (GEMMA, NEMOTRON, GROQ, GEMINI)})
    with pytest.raises(LLMProviderError) as info:
        await make(net).generate(REQ)
    assert "nvidia-gemma: LLMProviderError" in str(info.value) and "gemini: LLMProviderError" in str(info.value)


async def test_all_rate_limited_lets_the_session_wait_for_the_soonest():
    net = Network(**{m: [limited(retry_after=s)] for m, s in ((GEMMA, 20), (NEMOTRON, 3), (GROQ, 9), (GEMINI, 40))})
    with pytest.raises(LLMRateLimitError) as info:
        await make(net).generate(REQ)
    assert info.value.retry_after == 3 and info.value.is_retryable


async def test_the_session_retries_the_whole_chain():
    net = Network(**{GEMMA: [limited(retry_after=0.01), (200, completion("second try"))]})
    one = [LINKS[0]]
    session = LLMClientSession(make(net, one), LLMConfig(provider="chain", model="chain", max_retries=1))
    chain_mod.reset_benches()
    assert (await session.generate(REQ)).content == "second try"


# ---------------------------------------------------------------------------
# Requests each provider gets
# ---------------------------------------------------------------------------


async def test_each_provider_gets_its_own_key_model_and_options():
    net = Network(**{GEMMA: [limited()]})
    await make(net).generate(REQ)
    gemma, nemotron = net.calls
    assert gemma["auth"] == "Bearer k1" and nemotron["auth"] == "Bearer k2"
    assert nemotron["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "chat_template_kwargs" not in gemma["body"]


async def test_a_model_that_refuses_json_mode_is_asked_again_without_it():
    refused = (400, {"error": {"message": "response_format json_object is not supported for this model"}})
    net = Network(**{GEMMA: [refused, (200, completion('{"ok": true}'))]})
    answer = await make(net).generate(LLMRequest(prompt="hi", response_format="json"))
    assert answer.provider == "nvidia-gemma"  # gemma still answers: no fall-through over one option
    first, second = net.calls
    assert first["body"]["response_format"] == {"type": "json_object"} and "response_format" not in second["body"]


async def test_other_bad_requests_move_on_without_dropping_json_mode():
    net = Network(**{GEMMA: [(400, {"error": {"message": "context length exceeded"}})]})
    answer = await make(net).generate(LLMRequest(prompt="hi", response_format="json"))
    assert answer.provider == "nvidia-nemotron" and net.models() == [GEMMA, NEMOTRON]


# ---------------------------------------------------------------------------
# Configuration from the environment
# ---------------------------------------------------------------------------


def test_default_chain_order_and_models(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nv")
    monkeypatch.setenv("GROQ_API_KEY", "gq")
    monkeypatch.setenv("GEMINI_API_KEY", "gm")
    links = chain_links()
    assert [(link.name, link.model) for link in links] == [
        ("nvidia-gemma", "google/gemma-4-31b-it"), ("nvidia-nemotron", "nvidia/nemotron-3-ultra-550b-a55b"),
        ("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3.8-flash")]
    assert links[0].base_url == NVIDIA_BASE_URL and links[0].api_key == "nv"


def test_providers_without_a_key_are_left_out(monkeypatch):
    monkeypatch.setenv("NVIDIA_GEMMA_API_KEY", "only-gemma")
    monkeypatch.setenv("GEMINI_API_KEY", "gm")
    assert [link.name for link in chain_links()] == ["nvidia-gemma", "gemini"]


def test_separate_nvidia_keys_and_thinking(monkeypatch):
    monkeypatch.setenv("NVIDIA_GEMMA_API_KEY", "g")
    monkeypatch.setenv("NVIDIA_NEMOTRON_API_KEY", "n")
    monkeypatch.setenv("NVIDIA_NEMOTRON_THINKING", "true")
    gemma, nemotron = chain_links()
    assert (gemma.api_key, nemotron.api_key) == ("g", "n")
    assert dict(nemotron.extra_body)["chat_template_kwargs"] == {"enable_thinking": True}


def test_custom_order(monkeypatch):
    monkeypatch.setenv("LLM_CHAIN", "groq, gemini, groq")
    monkeypatch.setenv("GROQ_API_KEY", "gq")
    monkeypatch.setenv("GEMINI_API_KEY", "gm")
    assert [link.name for link in chain_links()] == ["groq", "gemini"]


def test_unknown_provider_in_the_chain_is_refused(monkeypatch):
    monkeypatch.setenv("LLM_CHAIN", "nvidia-gemma,openai")
    with pytest.raises(LLMConfigurationError, match="openai"):
        chain_links()


def test_chain_without_keys_is_a_configuration_error(monkeypatch):
    config = LLMConfig(provider="chain", model="chain")
    assert not config.is_configured
    with pytest.raises(LLMConfigurationError, match="NVIDIA_API_KEY"):
        get_llm_provider(config)


def test_factory_builds_the_chain(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gq")
    provider = get_llm_provider(LLMConfig(provider="chain", model="chain"))
    assert isinstance(provider, ChainProvider) and provider.names == ["groq"]


def test_keys_never_appear_in_repr(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-SECRET")
    assert "SECRET" not in repr(chain_links())


def test_system_info_lists_the_chain_and_says_ai_runs_in_the_cloud(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("LLM_PROVIDER", "chain")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv")
    monkeypatch.setenv("GEMINI_API_KEY", "gm")
    chain_mod.bench("nvidia-gemma", 120)
    info = TestClient(app).get("/api/system").json()
    assert info["privacy"]["ai_processing"] == "cloud"
    assert [(c["name"], c["benched_seconds"] > 100) for c in info["llm"]["chain"]] == [
        ("nvidia-gemma", True), ("nvidia-nemotron", False), ("gemini", False)]
    assert "nv" not in json.dumps(info["llm"]).replace("nvidia", "")


async def test_auth_failure_everywhere_is_an_authentication_error():
    net = Network(**{m: [(401, {"error": "bad key"})] for m in (GEMMA, NEMOTRON, GROQ, GEMINI)})
    with pytest.raises(LLMAuthenticationError):
        await make(net).generate(REQ)
