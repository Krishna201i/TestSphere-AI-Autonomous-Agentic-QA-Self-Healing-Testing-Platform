"""
security/ai.py
==============
AI triage layer for the Attacker Agent (module 5.3, AI slice).

The rule-based scanners (``passive_scanner``/``active_scanner``) always run and
own the facts.  When a real model is configured, this layer takes the findings
they already produced and asks the model to:

  * **prioritize** — rank what to fix first across the whole result,
  * **explain** — one plain-English sentence on the real-world risk,
  * **fix** — concrete remediation steps tailored to this finding.

Design rules (same contract as ``backend/pipeline/ai_plan.py``):

  * It never contacts the target.  It only reads findings produced in scope,
    so it cannot widen scope or be used for SSRF.
  * It degrades to nothing: any model/parse/timeout failure returns ``{}`` and
    the caller keeps the rule-based findings exactly as they were.
  * It cannot invent findings.  Output is matched back to real findings by
    ``check_id``; anything the model makes up is dropped.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

from security.findings import Finding

logger = logging.getLogger("testsphere.security.ai")

# Keep the prompt (and cost) bounded: triage the most severe findings only.
MAX_FINDINGS = 20
# Clamp evidence so one noisy finding cannot blow up the prompt.
_MAX_EVIDENCE = 4


class AIInsight(BaseModel):
    """The model's take on one finding, matched back by ``check_id``."""

    priority: int = Field(0, description="1 = fix first; larger = less urgent")
    summary: str = Field("", description="One-line risk statement in plain English")
    explanation: str = Field("", description="Why it matters / how it could be abused")
    remediation: str = Field("", description="Concrete steps to fix it")


def enabled() -> bool:
    """True when AI triage should run (mirrors the planner's gate)."""
    from agents.llm.config import LLMConfig
    from backend.config import settings

    mode = settings.SECURITY_AI
    if mode == "off":
        return False
    if mode == "on":
        return True
    # "auto": on only when a real (non-mock) provider is configured
    return LLMConfig.from_env().provider != "mock"


def _finding_digest(findings: list[Finding]) -> list[dict[str, Any]]:
    """Compact, model-facing view of each finding (no secrets, no raw headers)."""
    out: list[dict[str, Any]] = []
    for f in findings[:MAX_FINDINGS]:
        out.append({
            "check_id": f.check_id,
            "title": f.title,
            "severity": f.severity.value,
            "component": f.component,
            "evidence": f.evidence[:_MAX_EVIDENCE],
            "root_cause": f.root_cause,
        })
    return out


_SYSTEM = (
    "You are a security triage assistant for an authorized web application scan. "
    "You are given findings that a scanner already confirmed against a target the "
    "operator is authorized to test. Do not invent new findings, do not suggest "
    "attacking other systems, and never ask to scan anything. For each finding, "
    "rank its fix priority, state the real-world risk in one sentence, briefly "
    "explain how it could be abused, and give concrete remediation steps."
)


def _build_prompt(target_url: str, findings: list[Finding]) -> str:
    import json

    digest = _finding_digest(findings)
    return (
        f"Target (already authorized and scanned): {target_url}\n"
        f"Findings (JSON):\n{json.dumps(digest, indent=2)}\n\n"
        "Return ONLY a JSON object of this exact shape:\n"
        '{\n  "findings": [\n'
        '    {"check_id": "<id from above>", "priority": <int, 1 = most urgent>,\n'
        '     "summary": "<one sentence>", "explanation": "<how it could be abused>",\n'
        '     "remediation": "<concrete steps>"}\n'
        "  ]\n}\n"
        "Include one entry per finding above, keyed by its check_id. No prose outside the JSON."
    )


async def triage(
    target_url: str,
    findings: list[Finding],
    *,
    client: Any = None,
    timeout: float | None = None,
) -> dict[str, AIInsight]:
    """Return ``{finding.key: AIInsight}`` for *findings*, or ``{}`` on any failure.

    ``client`` is an ``LLMClientSession`` (built from env when omitted) — passing
    one keeps this testable without the network.
    """
    if not findings:
        return {}

    from agents.llm.exceptions import LLMError
    from agents.llm.schemas import LLMRequest
    from backend.config import settings

    if timeout is None:
        timeout = settings.SECURITY_AI_TIMEOUT

    if client is None:
        try:
            from agents.llm.factory import create_llm_client

            client = create_llm_client()
        except Exception as exc:  # noqa: BLE001 - misconfigured provider, missing key, …
            logger.warning("security AI triage disabled: %s", exc)
            return {}

    request = LLMRequest(
        prompt=_build_prompt(target_url, findings),
        system_instruction=_SYSTEM,
        response_format="json",
    )

    try:
        raw = await asyncio.wait_for(client.generate_json(request), timeout=timeout)
    except (TimeoutError, LLMError) as exc:
        logger.warning("security AI triage failed (%s); keeping rule-based findings", exc)
        return {}
    except Exception as exc:  # noqa: BLE001 - never let triage break a scan
        logger.warning("security AI triage errored (%s); keeping rule-based findings", exc)
        return {}

    return _match(raw, findings)


def _match(raw: dict[str, Any], findings: list[Finding]) -> dict[str, AIInsight]:
    """Attach model output to real findings by ``check_id``; drop anything else."""
    items = raw.get("findings") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return {}

    # A check_id can map to several findings (same check, different components);
    # apply the model's note to each of them.
    by_check: dict[str, list[Finding]] = {}
    for f in findings:
        by_check.setdefault(f.check_id, []).append(f)

    insights: dict[str, AIInsight] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        check_id = item.get("check_id")
        targets = by_check.get(check_id)
        if not targets:
            continue  # model invented an id; ignore it
        try:
            insight = AIInsight(
                priority=int(item.get("priority", 0) or 0),
                summary=str(item.get("summary", "")).strip(),
                explanation=str(item.get("explanation", "")).strip(),
                remediation=str(item.get("remediation", "")).strip(),
            )
        except (TypeError, ValueError):
            continue
        for f in targets:
            insights[f.key] = insight
    return insights
