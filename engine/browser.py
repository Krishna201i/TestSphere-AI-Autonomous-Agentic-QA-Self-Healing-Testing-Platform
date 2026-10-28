"""
engine/browser.py
=================
Playwright session manager for the TestSphere-AI QA engine.

Provides ``BrowserSession``, an async context manager that owns the full
Playwright → Browser → BrowserContext → Page lifecycle.  Callers get
fresh pages via ``new_page()`` and never touch the raw playwright objects.

Responsibilities
----------------
- Launch / teardown Chromium (headless toggle, slow-mo, viewport).
- Manage a single ``BrowserContext`` per test run so cookies / storage are
  isolated between runs.
- Optionally capture a Playwright trace (zip) written to *trace_path*.
- Expose ``new_page()`` as the only caller-facing surface.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

try:
    from playwright.async_api import (
        Browser,
        BrowserContext,
        Page,
        Playwright,
        async_playwright,
    )
    PLAYWRIGHT_INSTALLED = True
except ImportError:
    Browser = object  # type: ignore
    BrowserContext = object  # type: ignore
    Page = object  # type: ignore
    Playwright = object  # type: ignore
    async_playwright = None
    PLAYWRIGHT_INSTALLED = False

from .egress import EgressProxy
from .schemas import EngineConfig

if TYPE_CHECKING:
    pass  # keep imports clean; Page/Browser imported above for runtime use

log = logging.getLogger(__name__)

# Process-wide outbound guard: called with the URL of every destination the
# browser connects to; raising refuses it.  The backend installs its SSRF check
# here so a test step cannot point the server's browser at internal addresses.
_request_guard: Callable[[str], None] | None = None


def set_request_guard(guard: Callable[[str], None] | None) -> None:
    """Install (or clear, with ``None``) the outbound guard for new sessions."""
    global _request_guard
    _request_guard = guard


# At most this many Chromium instances at once per process (each takes
# ~150-300 MB); further sessions wait for a free slot.
MAX_BROWSERS = max(1, int(os.getenv("ENGINE_MAX_BROWSERS", "2")))
_slots: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = weakref.WeakKeyDictionary()


def _browser_slots() -> asyncio.Semaphore:
    """The running loop's browser semaphore (a semaphore is bound to one loop)."""
    loop = asyncio.get_running_loop()
    if loop not in _slots:
        _slots[loop] = asyncio.Semaphore(MAX_BROWSERS)
    return _slots[loop]


_install_lock = threading.Lock()
_install_state: dict = {"attempted": False, "error": None}  # Chromium (reported in /api/system)
_other_installs: dict[str, str | None] = {}  # firefox / webkit -> error or None


def _is_missing_browser(exc: BaseException) -> bool:
    return "Executable doesn't exist" in str(exc)


def install_browser(name: str) -> str | None:
    """Download *name* for this Playwright version, once per process (see ``install_chromium``)."""
    if name == "chromium":
        return install_chromium()
    with _install_lock:
        if name in _other_installs:
            return _other_installs[name]
        log.warning("%s is missing; installing it now (one-time, can take a minute)...", name)
        try:
            subprocess.run([sys.executable, "-m", "playwright", "install", name],
                           check=True, capture_output=True, text=True, timeout=600)
            _other_installs[name] = None
        except (OSError, subprocess.SubprocessError) as exc:
            detail = getattr(exc, "stderr", None) or str(exc)
            _other_installs[name] = f"automatic {name} install failed: {detail.strip()[-400:]}"
            log.error("%s", _other_installs[name])
        return _other_installs[name]


def install_chromium() -> str | None:
    """Download Chromium for this Playwright version, once per process.

    Hosts whose build step did not install the browser (or dropped it before
    runtime) recover on the first test instead of failing every run.  Returns
    None on success, else the reason it failed (cached, so later tests fail fast).
    """
    with _install_lock:
        if _install_state["attempted"]:
            return _install_state["error"]
        _install_state["attempted"] = True
        log.warning("Chromium is missing; installing it now (one-time, can take a minute)...")
        try:
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                           check=True, capture_output=True, text=True, timeout=600)
            log.warning("Chromium installed at runtime.")
        except (OSError, subprocess.SubprocessError) as exc:
            detail = getattr(exc, "stderr", None) or str(exc)
            _install_state["error"] = f"automatic Chromium install failed: {detail.strip()[-400:]}"
            log.error("%s", _install_state["error"])
        return _install_state["error"]


def chromium_status() -> dict:
    """Whether this Playwright's Chromium is on disk (for /api/system)."""
    if not PLAYWRIGHT_INSTALLED:
        return {"installed": False, "path": None, "error": "playwright package missing"}
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            path = pw.chromium.executable_path
        return {"installed": Path(path).exists(), "path": path, "error": _install_state["error"]}
    except Exception as exc:  # noqa: BLE001 - e.g. called inside a running event loop
        return {"installed": None, "path": None, "error": str(exc)[:200]}


class BrowserSession:
    """
    Async context manager that manages the Playwright browser lifecycle.

    Usage::

        async with BrowserSession(config) as session:
            page = await session.new_page()
            await page.goto("https://example.com")

    Parameters
    ----------
    config:
        Engine configuration controlling headless mode, slow-mo, tracing, etc.
    trace_path:
        If supplied (and ``config.tracing_enabled`` is True), the Playwright
        trace zip is written here on exit.  Defaults to
        ``{config.artifacts_dir}/_traces/session.zip``.
    """

    def __init__(
        self,
        config: EngineConfig,
        trace_path: str | None = None,
    ) -> None:
        self._config = config
        self._trace_path = trace_path
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._egress: EgressProxy | None = None
        self._slot: asyncio.Semaphore | None = None

    # ------------------------------------------------------------------
    # Async context-manager protocol
    # ------------------------------------------------------------------

    async def __aenter__(self) -> BrowserSession:
        if not PLAYWRIGHT_INSTALLED or async_playwright is None:
            raise RuntimeError(
                "Playwright is not installed in the environment. Please run 'pip install playwright && playwright install chromium' to enable browser automation."
            )
        slots = _browser_slots()
        if slots.locked():
            log.info("All %d browser slots busy; waiting for one", MAX_BROWSERS)
        await slots.acquire()
        self._slot = slots
        try:
            await self._open()
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def _open(self) -> None:
        if _request_guard is not None:
            self._egress = EgressProxy(_request_guard)
            self._proxy_url = await self._egress.start()
        self._pw = await async_playwright().start()
        log.debug(
            "Launching %s headless=%s slow_mo=%d",
            self._config.browser,
            self._config.headless,
            self._config.slow_mo_ms,
        )
        try:
            self._browser = await self._launch()
        except Exception as exc:
            if not _is_missing_browser(exc):
                raise
            failure = await asyncio.to_thread(install_browser, self._config.browser)
            if failure:
                raise RuntimeError(f"{exc}\n({failure})") from exc
            self._browser = await self._launch()
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )
        if self._config.tracing_enabled:
            await self._context.tracing.start(screenshots=True, snapshots=True)
            log.debug("Tracing started")

    async def _launch(self) -> Browser:
        name = self._config.browser
        options: dict = {"headless": self._config.headless, "slow_mo": self._config.slow_mo_ms}
        if self._egress:
            # Every request, localhost included, must reach the guard's proxy:
            # "<-loopback>" stops Chromium sending localhost straight past it,
            # and Firefox needs its own preferences for the same
            options["proxy"] = {"server": self._proxy_url, "bypass": "<-loopback>" if name == "chromium" else ""}
            if name == "firefox":
                options["firefox_user_prefs"] = {
                    "network.proxy.allow_hijacking_localhost": True,
                    "network.proxy.no_proxies_on": "",
                }
        return await getattr(self._pw, name).launch(**options)

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        try:
            await self._stop_tracing()
            if self._context is not None:
                await self._context.close()
            if self._browser is not None:
                await self._browser.close()
            if self._pw is not None:
                await self._pw.stop()
            if self._egress is not None:
                await self._egress.close()
            log.debug("BrowserSession closed")
        finally:
            if self._slot is not None:
                self._slot.release()
                self._slot = None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    async def new_page(self) -> Page:
        """Create and return a new browser page within the current context."""
        if self._context is None:
            raise RuntimeError("BrowserSession is not active; use as async context manager")
        page = await self._context.new_page()
        log.debug("New page created: %s", id(page))
        return page

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _stop_tracing(self) -> None:
        """Save trace zip if tracing was enabled."""
        if not self._config.tracing_enabled or self._context is None:
            return
        path = self._trace_path or str(
            Path(self._config.artifacts_dir) / "_traces" / "session.zip"
        )
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        await self._context.tracing.stop(path=path)
        log.info("Trace saved to %s", path)
