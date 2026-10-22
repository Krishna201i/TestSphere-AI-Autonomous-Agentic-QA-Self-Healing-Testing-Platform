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

Limitation: the guard resolves the host and the proxy then connects by name,
so a DNS answer that changes between the two lookups (DNS rebinding) is not
caught here.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
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
        self._verdicts: dict[tuple[str, int], str | None] = {}
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

    async def _refusal(self, host: str, port: int, url: str) -> str | None:
        """Why *host:port* may not be contacted, or None (one check per destination)."""
        key = (host.lower(), port)
        if key not in self._verdicts:
            try:
                await asyncio.to_thread(self._guard, url)
                self._verdicts[key] = None
            except Exception as exc:  # noqa: BLE001 - any guard error means refuse
                self._verdicts[key] = str(exc) or type(exc).__name__
        return self._verdicts[key]

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

        reason = await self._refusal(host, port, url)
        if reason:
            # Drop without a response: Chromium would render a proxy's 403 as
            # an ordinary page, and the step that navigated there would pass.
            log.warning("Blocked browser connection to %s:%s: %s", host, port, reason)
            return
        try:
            # Race IPv6/IPv4 like browsers do: a dead IPv6 route must not stall the run
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, happy_eyeballs_delay=0.25), timeout=15)
        except (TimeoutError, OSError):
            await _reply(writer, 502, "Bad Gateway")
            return

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
