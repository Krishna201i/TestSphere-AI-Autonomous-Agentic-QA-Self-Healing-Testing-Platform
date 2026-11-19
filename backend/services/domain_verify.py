"""
TestSphere-AI — Proof that a project owns the site it actively scans.

Active scanning sends attack payloads (XSS, SQL injection, open redirect).
Pointing it at someone else's site is an attack, so before an active scan the
project owner proves control of the host by publishing a token, as commercial
scanners require: the file ``/.well-known/testsphere-verify.txt`` on the site
holds the project's token.

- The check is a plain GET through the server's SSRF guard (public addresses
  only on a hosted server), with no redirects followed, so ownership cannot be
  borrowed from another site.
- A verification covers one host for one owner and lasts ``VALID_DAYS``.
- Loopback is exempt (local development), as is a server without sign-in.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

from backend.config import _hosted, settings
from backend.database.store import Record, Store, now_iso
from backend.models import PROJECTS
from backend.netguard import BlockedTargetError, PinnedTransport

WELL_KNOWN_PATH = "/.well-known/testsphere-verify.txt"
VALID_DAYS = 30
_TIMEOUT = 10.0


def required() -> bool:
    """Whether active scans need a verified host (REQUIRE_DOMAIN_VERIFICATION)."""
    mode = settings.REQUIRE_DOMAIN_VERIFICATION
    if mode in ("on", "true", "1"):
        return True
    if mode in ("off", "false", "0"):
        return False
    return _hosted() and settings.AUTH_REQUIRED  # auto: a public server with accounts


def host_of(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").lower()


def _exempt(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


def token_for(db: Store, project: Record) -> str:
    """The project's verification token (made on first use)."""
    if project.get("verify_token"):
        return project["verify_token"]
    token = "testsphere-verify=" + secrets.token_hex(16)
    db.update(PROJECTS, project["id"], verify_token=token)
    return token


def instructions(db: Store, project: Record) -> dict[str, Any]:
    """What the owner must publish, and the current state."""
    host = host_of(project.get("app_url"))
    parts = urlsplit(project.get("app_url") or "")
    return {
        "host": host,
        "token": token_for(db, project),
        "file_url": f"{parts.scheme or 'https'}://{parts.netloc}{WELL_KNOWN_PATH}" if host else None,
        "verified_host": project.get("verified_host"),
        "verified_at": project.get("verified_at"),
        "valid_days": VALID_DAYS,
        "how": f"Publish a file at {WELL_KNOWN_PATH} on your site whose content is the token, "
               "then ask TestSphere to check it. Active scans of this host are allowed for 30 days.",
    }


async def check(db: Store, project: Record) -> tuple[bool, str]:
    """Fetch the site's verification file; on success record the host as verified."""
    url = project.get("app_url") or ""
    host = host_of(url)
    if not host:
        return False, "The project has no app URL."
    token = token_for(db, project)
    parts = urlsplit(url)
    file_url = f"{parts.scheme}://{parts.netloc}{WELL_KNOWN_PATH}"
    try:
        async with httpx.AsyncClient(transport=PinnedTransport(), timeout=_TIMEOUT, follow_redirects=False) as http:
            response = await http.get(file_url, headers={"User-Agent": "TestSphere-DomainVerify/1.0"})
    except BlockedTargetError as exc:
        return False, str(exc)
    except httpx.HTTPError as exc:
        return False, f"Could not fetch {file_url}: {type(exc).__name__}"
    if response.status_code != 200:
        return False, f"{file_url} answered HTTP {response.status_code} (redirects are not followed)."
    if token not in {line.strip() for line in response.text.splitlines()}:
        return False, f"{file_url} does not contain this project's token."
    db.update(PROJECTS, project["id"], verified_host=host, verified_at=now_iso())
    return True, f"{host} is verified for {VALID_DAYS} days."


def refusal(db: Store, uid: str | None, url: str | None) -> str | None:
    """Why *uid* may not actively scan *url* for lack of proven ownership, or None."""
    if not required():
        return None
    host = host_of(url)
    if not host or _exempt(host):
        return None
    since = datetime.now(UTC) - timedelta(days=VALID_DAYS)
    for project in db.find(PROJECTS, owner_uid=uid, verified_host=host):
        try:
            if datetime.fromisoformat(project.get("verified_at") or "") >= since:
                return None
        except ValueError:
            continue
    return (f"Ownership of {host} is not verified: publish your project's token at {WELL_KNOWN_PATH} "
            "and verify it (Projects → domain verification) before active scanning")
