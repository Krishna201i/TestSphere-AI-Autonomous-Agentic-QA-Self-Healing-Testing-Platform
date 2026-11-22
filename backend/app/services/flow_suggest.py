"""
TestSphere-AI — Critical user flows worth testing, from the codebase and the live page.

The repository blueprint (routes, frameworks, existing test suites, auth risks)
and the analyzed start page say what the app does.  The model ranks the flows
a user depends on most (sign in, sign up, checkout, search ...) and writes each
as a plain-English test description that Test Studio turns into steps.
Without a model, rules find the same kinds of flow from route names and forms.

The model only sees a summary: route paths, framework names, element labels.
Page text is fenced as untrusted; the answer is data the user reviews.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

MAX_FLOWS = 8
MAX_ROUTES_IN_PROMPT = 60
RISKS = ("high", "medium", "low")

_KINDS = [
    # (name, path words, why, instruction, risk)
    ("Sign in", r"log-?in|sign-?in|auth|session", "Every signed-in feature depends on it.",
     "Log in as {user} with password {password} and check the page no longer shows the sign-in form", "high"),
    ("Sign up", r"sign-?up|register|join|create-?account", "New users cannot start without it.",
     "Sign up with a new email and a strong password and check the account is created", "high"),
    ("Checkout", r"checkout|cart|basket|order|payment|pay\b", "It is where revenue happens.",
     "Add the first product to the cart, open the cart and check it shows 1 item", "high"),
    ("Password reset", r"forgot|reset|password", "Locked-out users depend on it.",
     "Open the password reset page, request a reset for {user} and check a confirmation is shown", "medium"),
    ("Search", r"search|query|find", "Users find content through it.",
     "Search for a common word and check results are shown", "medium"),
    ("Contact form", r"contact|support|feedback", "It is how users reach you.",
     "Fill in the contact form and submit it and check a thank-you message is shown", "medium"),
    ("Profile", r"profile|account|settings|me\b", "Users manage their account there.",
     "Open the account settings page and check the user's details are shown", "low"),
]


def _values(profile_data: dict[str, str] | None) -> dict[str, str]:
    data = profile_data or {}
    return {"user": data.get("username") or data.get("email") or "<user name>",
            "password": data.get("password") and "the configured password" or "<password>"}


def rule_flows(blueprint: dict[str, Any] | None, analysis: dict[str, Any], test_data: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Flows found from route names and the page's forms, most important first."""
    routes = [r for r in (blueprint or {}).get("routes") or [] if isinstance(r, dict)]
    paths = [str(r.get("path") or "") for r in routes]
    inv = analysis.get("elements_inventory") or {}
    inputs = inv.get("inputs") or []
    has_password = any(i.get("type") == "password" for i in inputs)
    page_words = " ".join([str(analysis.get("url") or ""), str(analysis.get("page_title") or ""),
                           *[str(b.get("text") or "") for b in inv.get("buttons") or []]]).lower()
    values = _values(test_data)
    flows: list[dict[str, Any]] = []
    for name, words, why, instruction, risk in _KINDS:
        rx = re.compile(words, re.IGNORECASE)
        hits = [p for p in paths if rx.search(p)]
        on_page = bool(rx.search(page_words)) or (name == "Sign in" and has_password)
        if not hits and not on_page:
            continue
        where = f" (route {hits[0]})" if hits else " (on the start page)"
        flows.append({"name": name, "why": why + where, "risk": risk, "instruction": instruction.format(**values),
                      "evidence": hits[:3] or ["start page"]})
    # Pages the code defines, beyond the flows: each should at least load
    seen = {e for f in flows for e in f["evidence"]}
    for r in routes:
        path = str(r.get("path") or "")
        if len(flows) >= MAX_FLOWS:
            break
        if r.get("method", "GET").upper() != "GET" or path in seen or "{" in path or ":" in path or "/api" in path or path == "/":
            continue
        flows.append({"name": f"Page {path}", "why": "A page your code serves.", "risk": "low",
                      "instruction": f"Open {path} and check the page loads and shows its heading", "evidence": [path]})
        seen.add(path)
    return flows[:MAX_FLOWS]


SYSTEM = (
    "You are the test planner of TestSphere, an autonomous QA platform. From a summary of a web app's codebase and "
    "its start page, list the user flows most worth testing, the ones whose failure hurts users or the business "
    "most, most important first. Answer with ONLY one JSON object:\n"
    '{"flows": [{"name": "short name", "why": "one sentence: why it matters", "risk": "high|medium|low", '
    '"instruction": "the test in plain English, as a tester would write it: what to do and what to check"}]}\n'
    f"At most {MAX_FLOWS} flows. Base them on the routes and elements given; do not invent pages. "
    "Never invent passwords: write <password> where one is needed. Each instruction ends with what to check."
)


def build_prompt(blueprint: dict[str, Any] | None, analysis: dict[str, Any]) -> str:
    from agents.llm.untrusted import fence
    from app.services.test_studio import element_list

    if blueprint:
        routes = [f"{r.get('method', 'GET')} {r.get('path')}" for r in (blueprint.get("routes") or [])[:MAX_ROUTES_IN_PROMPT]
                  if isinstance(r, dict)]
        code = (f"Frameworks: {', '.join(blueprint.get('frameworks') or []) or 'unknown'}\n"
                f"Existing test suites: {', '.join(s.get('framework', '?') for s in blueprint.get('test_suites') or []) or 'none'}\n"
                f"Routes ({len(blueprint.get('routes') or [])}):\n" + ("\n".join(routes) or "(none found)"))
    else:
        code = "(no repository linked: plan from the page alone)"
    page = f"URL: {analysis.get('url')}\nTitle: {analysis.get('page_title') or ''}\n{element_list(analysis)}"
    return f"Codebase summary:\n{fence('code', code)}\n\nStart page:\n{fence('page', page)}"


def clean_flows(data: Any) -> list[dict[str, Any]]:
    flows = data.get("flows") if isinstance(data, dict) else None
    out = []
    for f in flows if isinstance(flows, list) else []:
        if not isinstance(f, dict) or not str(f.get("instruction") or "").strip():
            continue
        risk = str(f.get("risk") or "medium").lower()
        out.append({"name": str(f.get("name") or "Flow").strip()[:80], "why": str(f.get("why") or "").strip()[:240],
                    "risk": risk if risk in RISKS else "medium", "instruction": str(f["instruction"]).strip()[:500],
                    "evidence": []})
    order = {r: i for i, r in enumerate(RISKS)}
    return sorted(out, key=lambda f: order[f["risk"]])[:MAX_FLOWS]


async def model_flows(blueprint: dict[str, Any] | None, analysis: dict[str, Any], llm: Any, *, timeout: float) -> list[dict[str, Any]]:
    from agents.llm.schemas import LLMRequest
    from agents.llm.untrusted import UNTRUSTED_RULE

    request = LLMRequest(prompt=build_prompt(blueprint, analysis), system_instruction=f"{SYSTEM}\n{UNTRUSTED_RULE}",
                         temperature=0.2, max_tokens=1500)
    flows = clean_flows(await asyncio.wait_for(llm.generate_json(request), timeout=timeout))
    if not flows:
        raise ValueError("the model suggested no flows")
    return flows
