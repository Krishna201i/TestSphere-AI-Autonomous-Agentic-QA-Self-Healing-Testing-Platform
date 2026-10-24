"""
TestSphere-AI — Run notifications (Slack incoming webhooks).

A project can name a Slack incoming-webhook URL; after each pipeline run a
message goes there when the run failed, errored or found regressions (or
after every run, with ``notify_on="always"``).  Only https://hooks.slack.com
URLs are accepted, so the server can never be pointed at another host.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from backend.config import settings

logger = logging.getLogger("testsphere.notify")

SLACK_HOST = "hooks.slack.com"
NOTIFY_CHOICES = ("failures", "always")


def check_slack_webhook(url: str | None) -> str | None:
    """'' clears; otherwise the URL must be an https Slack incoming webhook."""
    if url is None:
        return None
    url = url.strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != SLACK_HOST or not parts.path.startswith("/services/") \
            or parts.port not in (None, 443) or parts.username or parts.password:
        raise ValueError("Slack webhook must be an https://hooks.slack.com/services/... URL "
                         "(Slack → Apps → Incoming Webhooks).")
    return url


def run_url(run_id: int) -> str | None:
    base = settings.DASHBOARD_URL.rstrip("/")
    return f"{base}/#/runs/{run_id}" if base else None


def should_notify(project: dict[str, Any], run: dict[str, Any]) -> bool:
    if not project.get("slack_webhook_url"):
        return False
    if project.get("notify_on") == "always":
        return run.get("status") in ("passed", "failed", "error")
    return run.get("status") in ("failed", "error") or bool(run.get("regressions"))


def slack_message(project: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """A short Slack message: verdict, counts, the first failures and a link."""
    s = run.get("summary") or {}
    status = run.get("status")
    icon = {"passed": ":white_check_mark:", "failed": ":x:", "error": ":warning:"}.get(status, ":grey_question:")
    head = f"{icon} *{project['name']}* · run #{run['id']} {status}"
    lines = [head]
    if s:
        counts = f"{s.get('passed', 0)}/{s.get('total', 0)} tests passed"
        extras = [f"{s[k]} {label}" for k, label in (("healed", "self-healed"), ("flaky", "flaky")) if s.get(k)]
        lines.append(" · ".join([counts, *extras]))
    if run.get("error"):
        lines.append(f"> {run['error'][:300]}")
    failures = [t for t in run.get("tests") or [] if t.get("status") == "FAILED"][:5]
    for t in failures:
        reason = (t.get("error") or "").split("\n")[0][:160]
        lines.append(f"• {t['name']}" + (f": {reason}" if reason else "") + (" _(quarantined)_" if t.get("quarantined") else ""))
    regressions = run.get("regressions") or []
    if regressions:
        lines.append(f"{len(regressions)} regression(s) since run #{s.get('previous_run_id')}")
    link = run_url(run["id"])
    text = "\n".join(lines)
    blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if link:
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Open run"}, "url": link}]})
    return {"text": head, "blocks": blocks}


async def notify_run(project: dict[str, Any], run: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Post the run to the project's Slack webhook if it should; never raises."""
    if not should_notify(project, run):
        return False
    try:
        url = check_slack_webhook(project["slack_webhook_url"])
    except ValueError:
        logger.warning("Project %s has an invalid Slack webhook; not notifying", project.get("id"))
        return False
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False, transport=transport) as client:
            resp = await client.post(url, json=slack_message(project, run))
        if resp.status_code >= 400:
            logger.warning("Slack rejected the notification for run #%s: HTTP %s %s", run["id"], resp.status_code, resp.text[:200])
            return False
        return True
    except httpx.HTTPError as exc:
        logger.warning("Slack notification for run #%s failed: %s", run["id"], exc)
        return False
