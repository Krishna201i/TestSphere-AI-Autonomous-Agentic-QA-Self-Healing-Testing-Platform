"""
TestSphere-AI — HTTP hardening for every response and request.

* Security headers.  TestSphere flags missing headers on other sites, so it
  sends them itself: a Content-Security-Policy for the dashboard (its own
  scripts, Google Fonts, Firebase sign-in), frame-ancestors/X-Frame-Options
  against clickjacking, nosniff, a referrer policy, and HSTS over HTTPS.  A
  route that sets its own policy (artifact downloads use ``sandbox``) keeps it.
* Request size limit.  Bodies over ``MAX_REQUEST_BYTES`` are refused with 413
  before they are read into memory or stored (GitHub webhooks get more room).
"""

from __future__ import annotations

from typing import Any

MAX_REQUEST_BYTES = 1 * 1024 * 1024
MAX_WEBHOOK_BYTES = 10 * 1024 * 1024

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://apis.google.com https://www.gstatic.com",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob: https:",
    "connect-src 'self' https://*.googleapis.com https://*.firebaseio.com https://*.firebaseapp.com",
    "frame-src https://*.firebaseapp.com https://*.web.app https://accounts.google.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
])

HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]


def _https(scope: dict[str, Any]) -> bool:
    if scope.get("scheme") == "https":
        return True
    for name, value in scope.get("headers") or []:
        if name == b"x-forwarded-proto":
            return value.split(b",")[0].strip() == b"https"
    return False


class HardeningMiddleware:
    """Pure ASGI: adds security headers and enforces the body size limit."""

    def __init__(self, app: Any, max_bytes: int = MAX_REQUEST_BYTES, webhook_bytes: int = MAX_WEBHOOK_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.webhook_bytes = webhook_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.webhook_bytes if "/webhooks/" in scope.get("path", "") else self.max_bytes
        length = next((v for k, v in scope.get("headers") or [] if k == b"content-length"), None)
        if length is not None and length.isdigit() and int(length) > limit:
            await self._too_large(send, limit)
            return

        received = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _TooLarge
            return message

        https = _https(scope)

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {k.lower() for k, _ in headers}
                extra = [(k, v) for k, v in HEADERS if k not in present]
                if b"content-security-policy" not in present:
                    extra.append((b"content-security-policy", CSP.encode()))
                if https and b"strict-transport-security" not in present:
                    extra.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message = {**message, "headers": headers + extra}
            await send(message)

        try:
            await self.app(scope, limited_receive, send_with_headers)
        except _TooLarge:
            await self._too_large(send, limit)

    @staticmethod
    async def _too_large(send: Any, limit: int) -> None:
        body = f'{{"detail":"Request body is larger than {limit // (1024 * 1024)} MB."}}'.encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class _TooLarge(Exception):
    pass
