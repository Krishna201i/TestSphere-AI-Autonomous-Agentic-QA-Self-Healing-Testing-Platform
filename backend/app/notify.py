"""
TestSphere-AI — Run notifications (chat webhooks).

A project can name an incoming-webhook URL for Slack, Discord, Google Chat or
Microsoft Teams (stored as ``slack_webhook_url``, its original name); after
each pipeline run a message goes there when the run failed, errored or found
regressions (or after every run, with ``notify_on="always"``).  Only those
services' webhook hosts are accepted, so the server can never be pointed at
another host.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from backend.config import settings

logger = logging.getLogger("testsphere.notify")

NOTIFY_CHOICES = ("failures", "always")


def webhook_kind(url: str) -> str | None:
    """Which chat service an https webhook URL belongs to, or None."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.port not in (None, 443) or parts.username or parts.password:
        return None
    host, path = (parts.hostname or "").lower(), parts.path
    if host == "hooks.slack.com" and path.startswith("/services/"):
        return "slack"
    if host in ("discord.com", "discordapp.com") and path.startswith("/api/webhooks/"):
        return "discord"
    if host == "chat.googleapis.com" and path.startswith("/v1/spaces/"):
        return "google_chat"
    # Teams: a Workflows (Power Automate) webhook, or a legacy connector
    if host.endswith((".logic.azure.com", ".api.powerplatform.com", ".webhook.office.com")):
        return "teams"
    return None


def check_alert_webhook(url: str | None) -> str | None:
    """'' clears; otherwise the URL must be a Slack, Discord, Google Chat or Teams webhook."""
    if url is None:
        return None
    url = url.strip()
    if not url:
        return ""
    if webhook_kind(url) is None:
        raise ValueError("Alert webhook must be an https incoming-webhook URL from Slack "
                         "(hooks.slack.com/services/...), Discord (discord.com/api/webhooks/...), "
                         "Google Chat (chat.googleapis.com/v1/spaces/...) or Microsoft Teams (a Workflows webhook).")
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


def _summary_lines(project: dict[str, Any], run: dict[str, Any], icon: str, bold: str) -> list[str]:
    """Verdict, counts, the first failures and regressions, in the service's markup."""
    s = run.get("summary") or {}
    lines = [f"{icon} {bold}{project['name']}{bold} · run #{run['id']} {run.get('status')}"]
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
    return lines


_ICONS = {"passed": "✅", "failed": "❌", "error": "⚠️"}


def slack_message(project: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """A short Slack message: verdict, counts, the first failures and a link."""
    icon = {"passed": ":white_check_mark:", "failed": ":x:", "error": ":warning:"}.get(run.get("status"), ":grey_question:")
    lines = _summary_lines(project, run, icon, "*")
    head = lines[0]
    link = run_url(run["id"])
    text = "\n".join(lines)
    blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if link:
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Open run"}, "url": link}]})
    return {"text": head, "blocks": blocks}


def chat_message(kind: str, project: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """The run message in the format *kind*'s webhook expects."""
    if kind == "slack":
        return slack_message(project, run)
    icon = _ICONS.get(run.get("status"), "❔")
    link = run_url(run["id"])
    if kind == "teams":
        lines = _summary_lines(project, run, icon, "**")
        card: dict[str, Any] = {
            "type": "AdaptiveCard", "version": "1.4",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "body": [{"type": "TextBlock", "text": line, "wrap": True} for line in lines],
        }
        if link:
            card["actions"] = [{"type": "Action.OpenUrl", "title": "Open run", "url": link}]
        return {"type": "message", "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}
    bold = "**" if kind == "discord" else "*"
    text = "\n".join(_summary_lines(project, run, icon, bold) + ([link] if link else []))
    return {"content": text[:2000]} if kind == "discord" else {"text": text}


async def notify_run(project: dict[str, Any], run: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Post the run to the project's chat webhook if it should; never raises."""
    if not should_notify(project, run):
        return False
    url = project["slack_webhook_url"]
    kind = webhook_kind(url)
    if kind is None:
        logger.warning("Project %s has an invalid alert webhook; not notifying", project.get("id"))
        return False
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False, transport=transport) as client:
            resp = await client.post(url, json=chat_message(kind, project, run))
        if resp.status_code >= 400:
            logger.warning("%s rejected the notification for run #%s: HTTP %s %s", kind, run["id"],
                           resp.status_code, resp.text[:200])
            return False
        return True
    except httpx.HTTPError as exc:
        logger.warning("%s notification for run #%s failed: %s", kind, run["id"], exc)
        return False
