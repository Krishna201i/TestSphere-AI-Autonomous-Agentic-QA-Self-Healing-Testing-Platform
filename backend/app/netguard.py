"""
TestSphere-AI — Outbound URL guard (SSRF protection).

Page analysis, link checks and browser runs fetch URLs that users type.  On a
public host that must never reach the server's own network: loopback, private
ranges, link-local (cloud metadata at 169.254.169.254) and other reserved
addresses are refused.  Local development keeps them (testing localhost apps
is the point there) unless ``ALLOW_PRIVATE_TARGETS`` says otherwise.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from app.config import settings


class BlockedTargetError(ValueError):
    """The URL points at an address this server may not contact."""


# IPv6 forms that carry an IPv4 address: NAT64 (IPv6-only networks reach
# public IPv4 sites through 64:ff9b::a.b.c.d) and IPv4-mapped (::ffff:a.b.c.d)
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _embedded_ipv4(ip: ipaddress._BaseAddress) -> ipaddress.IPv4Address | None:
    if ip.version != 6:
        return None
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if ip in _NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def _blocked(ip: ipaddress._BaseAddress) -> bool:
    inner = _embedded_ipv4(ip)
    if inner is not None:
        return _blocked(inner)  # judge the IPv4 site it stands for
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified)


async def guard_request(request) -> None:
    """httpx request hook: re-checks every hop, so a redirect cannot reach an internal address."""
    await asyncio.to_thread(check_target, str(request.url))


class PinnedTransport(httpx.AsyncBaseTransport):
    """httpx transport that connects only to addresses it has checked.

    ``check_target`` resolves a host to judge it, but httpx would resolve it
    again to connect, so a DNS answer that changes in between (DNS
    rebinding) could reach an internal address.  This transport resolves each
    request's host once, refuses it if any address is internal, and connects
    to the checked address itself; the original name stays in the Host header
    and is used for TLS (SNI and certificate verification).  Every redirect
    hop is a new request, so it is checked the same way.

    Keep-alive is off: hosts that share an address (a CDN, www and the apex)
    must never share a connection made for the other name.
    """

    def __init__(self, *, verify: bool = True) -> None:
        self._inner = httpx.AsyncHTTPTransport(verify=verify, limits=httpx.Limits(max_keepalive_connections=0))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme not in ("http", "https") or not url.host:
            raise BlockedTargetError(f"Only http(s) URLs can be tested, not {str(url)!r}.")
        if settings.ALLOW_PRIVATE_TARGETS:
            return await self._inner.handle_async_request(request)
        addresses = await _checked_addresses(url.host, url.port or (443 if url.scheme == "https" else 80))
        # Like a normal client, try each address until one connects (a dead
        # IPv4 or IPv6 route must not fail the request); a connect failure
        # happens before the request is sent, so retrying is safe
        for i, address in enumerate(addresses):
            pinned = httpx.Request(
                request.method, url.copy_with(host=address), headers=request.headers, stream=request.stream,
                extensions={**request.extensions, "sni_hostname": url.host},
            )
            try:
                return await self._inner.handle_async_request(pinned)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if i == len(addresses) - 1:
                    raise
        raise AssertionError("unreachable")  # pragma: no cover - addresses is never empty

    async def aclose(self) -> None:
        await self._inner.aclose()


async def _checked_addresses(host: str, port: int) -> list[str]:
    """Every address *host* resolves to, in the resolver's preferred order,
    after checking that none of them is internal."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedTargetError(f"{host} does not resolve: {exc.strerror or exc}") from exc
    addresses = list(dict.fromkeys(info[4][0].split("%")[0] for info in infos))
    if not addresses:
        raise BlockedTargetError(f"{host} does not resolve")
    for address in addresses:
        if _blocked(ipaddress.ip_address(address)):
            raise BlockedTargetError(
                f"{host} resolves to {address}, a private or internal address. This server only tests public sites."
            )
    return addresses


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
