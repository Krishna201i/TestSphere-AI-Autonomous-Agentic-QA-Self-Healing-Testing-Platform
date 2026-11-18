"""
TestSphere-AI — Deploy hook validation (no imports beyond settings, so the
API schemas can use it).  Hooks are only ever called on allow-listed hosts.

A GitHub Actions ``workflow_dispatch`` URL is a hook too (any host, AWS
included, deployed by a workflow): it is called with the project owner's
connected GitHub token, so on api.github.com only that one endpoint is allowed.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.config import settings

GITHUB_API = "api.github.com"
DEFAULT_HOOK_HOSTS = ("api.render.com", "api.vercel.com", "api.netlify.com", GITHUB_API)
GITHUB_DISPATCH = re.compile(r"/repos/[\w.-]+/[\w.-]+/actions/workflows/[\w.-]+/dispatches")


class DeployConfigError(ValueError):
    """A hook URL this server will not call."""


def hook_hosts() -> set[str]:
    extra = {h.strip().lower() for h in settings.DEPLOY_HOOK_HOSTS.split(",") if h.strip()}
    return set(DEFAULT_HOOK_HOSTS) | extra


def check_hook_url(url: str | None, what: str = "Deploy hook") -> str | None:
    """'' clears; otherwise https on an allow-listed host, no credentials in the URL."""
    if url is None:
        return None
    url = url.strip()
    if not url:
        return ""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        raise DeployConfigError(f"{what} must be a plain https:// URL.")
    if host not in hook_hosts():
        raise DeployConfigError(f"{what} host {host or '?'} is not allowed ({', '.join(sorted(hook_hosts()))}; "
                                "more with DEPLOY_HOOK_HOSTS).")
    if host == GITHUB_API and not GITHUB_DISPATCH.fullmatch(parts.path):
        raise DeployConfigError(f"{what} on GitHub must be a workflow dispatch URL: "
                                "https://api.github.com/repos/<owner>/<repo>/actions/workflows/<file>/dispatches")
    return url


def provider_of(url: str | None) -> str | None:
    host = (urlsplit(url or "").hostname or "").lower()
    return {"api.render.com": "render", "api.vercel.com": "vercel", "api.netlify.com": "netlify",
            GITHUB_API: "github"}.get(host, host or None)


def redeploys_a_commit(url: str | None) -> bool:
    """Whether the hook can deploy a given commit, so a rollback can reuse it."""
    return provider_of(url) in ("render", "github")


def github_dispatch(hook: str) -> tuple[str, str]:
    """(endpoint to POST, branch the workflow runs from: ``?ref=``, default main)."""
    parts = urlsplit(hook)
    ref = dict(parse_qsl(parts.query)).get("ref") or "main"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")), ref


def with_ref(hook: str, commit: str) -> str:
    """Render deploy hooks deploy a given commit with ``&ref=<sha>``."""
    parts = urlsplit(hook)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "ref"] + [("ref", commit)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


