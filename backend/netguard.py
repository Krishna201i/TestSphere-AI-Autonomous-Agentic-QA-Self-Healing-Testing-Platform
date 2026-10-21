"""
TestSphere-AI — Outbound URL guard (SSRF protection).

Page analysis, link checks and browser runs fetch URLs that users type.  On a
public host that must never reach the server's own network: loopback, private
ranges, link-local (cloud metadata at 169.254.169.254) and other reserved
addresses are refused.  Local development keeps them (testing localhost apps
is the point there) unless ``ALLOW_PRIVATE_TARGETS`` says otherwise.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from backend.config import settings


class BlockedTargetError(ValueError):
    """The URL points at an address this server may not contact."""


def _blocked(ip: ipaddress._BaseAddress) -> bool:
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified)


async def guard_request(request) -> None:
    """httpx request hook: re-checks every hop, so a redirect cannot reach an internal address."""
    check_target(str(request.url))


def check_target(url: str) -> None:
    """Raise ``BlockedTargetError`` unless *url* is http(s) to a public address
    (or private targets are allowed on this server)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise BlockedTargetError(f"Only http(s) URLs can be tested, not {url!r}.")
    if settings.ALLOW_PRIVATE_TARGETS:
        return
    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedTargetError(f"{host} does not resolve: {exc.strerror or exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if _blocked(ip):
            raise BlockedTargetError(
                f"{host} resolves to {ip}, a private or internal address. This server only tests public sites."
            )
