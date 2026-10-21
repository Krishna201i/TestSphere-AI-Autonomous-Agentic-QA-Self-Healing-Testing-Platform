"""
security/scope.py
=================
Authorization scope for security testing.

Nothing in ``security/`` may send a request to a host that is not on the
allowlist.  The default scope is loopback only, so scanning anything else
requires an explicit, deliberate ``allowed_hosts`` entry — the synopsis'
"authorized targets only" rule (Appendix C), enforced in code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class OutOfScopeError(PermissionError):
    """Raised when a URL falls outside the authorized scan scope."""


@dataclass(frozen=True)
class ScopePolicy:
    """Allowlist of hosts a scan may touch.

    Entries are hostnames (``example.test``) or ``host:port`` pairs
    (``127.0.0.1:8000``).  A bare hostname allows every port on that host.
    """

    allowed_hosts: frozenset[str] = field(default_factory=lambda: LOOPBACK_HOSTS)

    @classmethod
    def of(cls, *hosts: str) -> ScopePolicy:
        return cls(frozenset(h.strip().lower() for h in hosts if h.strip()))

    def check(self, url: str) -> None:
        """Raise ``OutOfScopeError`` unless *url* is http(s) on an allowed host."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise OutOfScopeError(f"Only http(s) URLs can be scanned, got {parts.scheme!r}")

        host = (parts.hostname or "").lower()
        if not host:
            raise OutOfScopeError(f"URL has no host: {url!r}")

        port = parts.port or (443 if parts.scheme == "https" else 80)
        if host in self.allowed_hosts or f"{host}:{port}" in self.allowed_hosts:
            return
        raise OutOfScopeError(
            f"{host}:{port} is not in the authorized scope "
            f"({', '.join(sorted(self.allowed_hosts))})"
        )

    def allows(self, url: str) -> bool:
        try:
            self.check(url)
        except OutOfScopeError:
            return False
        return True


def is_loopback(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() in LOOPBACK_HOSTS
