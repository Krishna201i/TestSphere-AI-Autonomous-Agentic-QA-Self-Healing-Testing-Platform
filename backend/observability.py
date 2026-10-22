"""
TestSphere-AI — Logging, request tracing and error reporting.

- ``configure_logging``: app loggers at ``LOG_LEVEL`` (default INFO), written
  as one JSON object per line when hosted (searchable in the host's log
  viewer) or as readable text locally; ``LOG_FORMAT=json|text`` overrides.
- ``RequestContextMiddleware``: gives every request an id (a well-formed
  incoming ``X-Request-ID`` is kept), echoes it in the response, stamps it on
  every log line written while handling the request, and logs one summary
  line per request (method, path, status, duration).
- ``init_error_reporting``: sends unhandled errors to Sentry when
  ``SENTRY_DSN`` is set; no personal data, no performance tracing.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import UTC, datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_access_log = logging.getLogger("testsphere.access")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, message, request_id, extras."""

    _STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "request_id", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if getattr(record, "request_id", None):
            entry["request_id"] = record.request_id
        entry.update({k: v for k, v in vars(record).items() if k not in self._STANDARD and not k.startswith("_")})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str, fmt: str) -> None:
    """Route the app's loggers (``testsphere.*``, ``engine``, ``agents``...) to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    for existing in [h for h in root.handlers if getattr(h, "_testsphere", False)]:
        root.removeHandler(existing)
    handler._testsphere = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2", "urllib3", "google", "grpc", "asyncio", "langsmith"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))


class RequestContextMiddleware:
    """Request id + one access-log line per HTTP request (pure ASGI, streaming-safe)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            path = scope.get("path", "")
            if path.startswith("/api") or status_code >= 500:  # skip static dashboard files
                level = logging.ERROR if status_code >= 500 else logging.WARNING if status_code >= 400 else logging.INFO
                _access_log.log(level, "%s %s -> %s (%sms)", scope.get("method"), path, status_code, duration_ms,
                                extra={"method": scope.get("method"), "path": path,
                                       "status": status_code, "duration_ms": duration_ms})
            request_id_var.reset(token)


def init_error_reporting(dsn: str, environment: str, release: str | None) -> bool:
    """Send unhandled exceptions to Sentry; False when the SDK is missing or the DSN is unset."""
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logging.getLogger("testsphere.backend").warning("SENTRY_DSN is set but sentry-sdk is not installed")
        return False
    sentry_sdk.init(dsn=dsn, environment=environment, release=release,
                    send_default_pii=False, traces_sample_rate=0.0)
    return True


def default_log_format() -> str:
    explicit = os.getenv("LOG_FORMAT", "").strip().lower()
    if explicit in ("json", "text"):
        return explicit
    from backend.config import _hosted

    return "json" if _hosted() else "text"
