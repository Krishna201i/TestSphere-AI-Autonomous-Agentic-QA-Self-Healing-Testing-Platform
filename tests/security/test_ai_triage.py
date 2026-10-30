"""
Tests for security/ai.py — the AI triage layer of the Attacker Agent.

The model is always stubbed: triage must never touch the network, must map
output back to real findings by ``check_id`` (dropping anything invented), and
must degrade to ``{}`` on any model/parse/timeout failure so the rule-based
findings survive untouched.
"""

import asyncio

import pytest

from agents.llm.exceptions import LLMResponseError
from security import Finding, FindingSource, Severity
from security.ai import AIInsight, _match, triage

pytestmark = pytest.mark.asyncio


def _finding(check_id: str, component: str = "https://app.test/", sev: Severity = Severity.HIGH) -> Finding:
    return Finding(check_id=check_id, source=FindingSource.SECURITY, title=f"{check_id} issue",
                   severity=sev, component=component, target_url="https://app.test/")


class _FakeClient:
    """Stand-in LLMClientSession: returns a canned dict or raises."""

    def __init__(self, payload=None, exc=None):
        self._payload = payload
        self._exc = exc
        self.calls = 0

    async def generate_json(self, request):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._payload


async def test_triage_maps_insights_by_key():
    f = _finding("SEC-HDR-CSP")
    client = _FakeClient(payload={"findings": [
        {"check_id": "SEC-HDR-CSP", "priority": 1, "summary": "No CSP",
         "explanation": "A reflected script would run.", "remediation": "Set Content-Security-Policy."}
    ]})
    out = await triage("https://app.test/", [f], client=client)
    assert set(out) == {f.key}
    assert out[f.key].priority == 1
    assert out[f.key].remediation.startswith("Set Content-Security-Policy")
    assert client.calls == 1


async def test_triage_drops_invented_check_ids():
    f = _finding("SEC-HDR-CSP")
    client = _FakeClient(payload={"findings": [
        {"check_id": "SEC-TOTALLY-MADE-UP", "priority": 1, "summary": "nope"},
    ]})
    out = await triage("https://app.test/", [f], client=client)
    assert out == {}


async def test_one_check_id_annotates_every_matching_finding():
    # Same check on two components -> both get the model's note.
    a = _finding("SEC-COOKIE-FLAGS", component="https://app.test/ (sid)")
    b = _finding("SEC-COOKIE-FLAGS", component="https://app.test/ (csrf)")
    client = _FakeClient(payload={"findings": [
        {"check_id": "SEC-COOKIE-FLAGS", "priority": 2, "summary": "Insecure cookies"},
    ]})
    out = await triage("https://app.test/", [a, b], client=client)
    assert set(out) == {a.key, b.key}
    assert out[a.key].summary == "Insecure cookies"


async def test_empty_findings_skips_the_model():
    client = _FakeClient(payload={"findings": []})
    out = await triage("https://app.test/", [], client=client)
    assert out == {}
    assert client.calls == 0


async def test_model_error_degrades_to_empty():
    f = _finding("SEC-HDR-CSP")
    client = _FakeClient(exc=LLMResponseError("bad json", provider="api"))
    out = await triage("https://app.test/", [f], client=client)
    assert out == {}  # caller keeps the rule-based finding as-is


async def test_timeout_degrades_to_empty():
    f = _finding("SEC-HDR-CSP")

    class _Slow:
        async def generate_json(self, request):
            await asyncio.sleep(1)
            return {"findings": []}

    out = await triage("https://app.test/", [f], client=_Slow(), timeout=0.01)
    assert out == {}


async def test_malformed_payload_shapes_are_ignored():
    f = _finding("SEC-HDR-CSP")
    for payload in ({}, {"findings": "not-a-list"}, {"findings": [42, "x"]}, "nonsense"):
        out = await triage("https://app.test/", [f], client=_FakeClient(payload=payload))
        assert out == {}


async def test_match_is_pure_and_defensive():
    f = _finding("SEC-HDR-FRAME")
    insights = _match({"findings": [{"check_id": "SEC-HDR-FRAME", "priority": "oops"}]}, [f])
    # non-int priority falls back without raising
    assert insights == {} or isinstance(insights[f.key], AIInsight)
