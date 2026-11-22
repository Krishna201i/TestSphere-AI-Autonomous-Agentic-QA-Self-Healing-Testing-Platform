"""
engine/egress.py
================
Outbound policy for the browser: a local forward proxy that every Chromium
connection goes through while a guard is installed.

Route interception is not enough for this: Chromium follows redirects (even
ones handed back through ``route.fulfill``) without consulting routes again,
so a public URL that redirects to an internal address would get through.  A
proxy sees each connection the browser opens, including every redirect hop,
subresource and websocket, as ``CONNECT host:port`` or an absolute-URI
request, and refuses it unless the guard accepts the destination.

The guard is any callable taking a URL and raising to refuse it; the backend
installs its SSRF check (``backend.netguard.check_target``) via
``engine.browser.set_request_guard``.

DNS rebinding: the proxy resolves each host once, checks every address it
resolved to, and connects only to those checked addresses (pinned for the
session), so a DNS answer that changes after the check cannot redirect the
connection to an internal address.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

_HEAD_LIMIT = 64 * 1024
_HOP_BY_HOP = ("proxy-connection:", "connection:", "keep-alive:", "proxy-authorization:")


class EgressProxy:
    """Forward proxy on 127.0.0.1 that applies *guard* to every destination."""

    def __init__(self, guard: Callable[[str], None]) -> None:
        self._guard = guard
        self._server: asyncio.base_events.Server | None = None
        # (host, port) -> (refusal or None, the checked addresses to connect to)
        self._verdicts: dict[tuple[str, int], tuple[str | None, list[str]]] = {}
        self._writers: set[asyncio.StreamWriter] = set()

    async def start(self) -> str:
        """Start listening; returns the proxy URL to hand to the browser."""
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0, limit=_HEAD_LIMIT)
        port = self._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        for writer in list(self._writers):
            writer.close()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._server.wait_closed(), timeout=2)

    async def _verdict(self, host: str, port: int, url: str) -> tuple[str | None, list[str]]:
        """Why *host:port* may not be contacted (or None) and the addresses that
        were checked, resolved once per destination for the whole session."""
        key = (host.lower(), port)
        if key not in self._verdicts:
            self._verdicts[key] = await self._check(host, port, url)
        return self._verdicts[key]

    async def _check(self, host: str, port: int, url: str) -> tuple[str | None, list[str]]:
        try:
            await asyncio.to_thread(self._guard, url)
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
            # IPv4 first: a dead IPv6 route must not stall the run
            ips = sorted({info[4][0].split("%")[0] for info in infos}, key=lambda ip: ":" in ip)
            if not ips:
                return f"{host} does not resolve", []
            scheme = urlsplit(url).scheme
            for ip in ips:  # the addresses actually connected to, not only the name
                await asyncio.to_thread(self._guard, f"{scheme}://{f'[{ip}]' if ':' in ip else ip}:{port}/")
        except Exception as exc:  # noqa: BLE001 - any guard or lookup error means refuse
            return str(exc) or type(exc).__name__, []
        return None, ips

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        try:
            await self._serve(reader, writer)
        except (TimeoutError, ConnectionError, OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
        lines = head.decode("latin-1").split("\r\n")
        method, target, version = lines[0].split(" ", 2)

        if method == "CONNECT":  # https and wss: an opaque tunnel to host:port
            host, _, port_text = target.rpartition(":")
            host, port = host.strip("[]"), int(port_text)
            url = f"https://{f'[{host}]' if ':' in host else host}:{port}/"
        else:  # plain http: absolute-URI request line
            parts = urlsplit(target)
            if parts.scheme != "http" or not parts.hostname:
                await _reply(writer, 400, "Bad Request")
                return
            host, port, url = parts.hostname, parts.port or 80, target

        reason, ips = await self._verdict(host, port, url)
        if reason:
            # Drop without a response: Chromium would render a proxy's 403 as
            # an ordinary page, and the step that navigated there would pass.
            log.warning("Blocked browser connection to %s:%s: %s", host, port, reason)
            return
        upstream = await _connect(ips, port)
        if upstream is None:
            await _reply(writer, 502, "Bad Gateway")
            return
        up_reader, up_writer = upstream

        if method == "CONNECT":
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
        else:
            # One request per upstream connection: a reused client connection
            # could otherwise carry a request for another host past the check.
            path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            headers = [line for line in lines[1:] if line and not line.lower().startswith(_HOP_BY_HOP)]
            request = "\r\n".join([f"{method} {path} {version}", *headers, "Connection: close", "", ""])
            up_writer.write(request.encode("latin-1"))  # nosemgrep: request-data-write - forwarding after the destination check
        await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))


async def _connect(ips: list[str], port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
    """Open a connection to the first checked address that answers (never by name)."""
    for ip in ips:
        try:
            return await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=5 if ":" in ip else 15)
        except (TimeoutError, OSError):
            continue
    return None


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        writer.close()


async def _reply(writer: asyncio.StreamWriter, code: int, text: str) -> None:
    writer.write(f"HTTP/1.1 {code} {text}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
    await writer.drain()
