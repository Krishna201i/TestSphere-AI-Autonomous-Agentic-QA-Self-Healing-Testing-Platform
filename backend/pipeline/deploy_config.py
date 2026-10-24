"""
TestSphere-AI — Deploy hook validation (no imports beyond settings, so the
API schemas can use it).  Hooks are only ever called on allow-listed hosts.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.config import settings

DEFAULT_HOOK_HOSTS = ("api.render.com", "api.vercel.com", "api.netlify.com")


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
    return url


def provider_of(url: str | None) -> str | None:
    host = (urlsplit(url or "").hostname or "").lower()
    return {"api.render.com": "render", "api.vercel.com": "vercel", "api.netlify.com": "netlify"}.get(host, host or None)


def with_ref(hook: str, commit: str) -> str:
    """Render deploy hooks deploy a given commit with ``&ref=<sha>``."""
    parts = urlsplit(hook)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "ref"] + [("ref", commit)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


