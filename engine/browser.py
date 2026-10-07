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

import logging
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

from .schemas import EngineConfig

if TYPE_CHECKING:
    pass  # keep imports clean; Page/Browser imported above for runtime use

log = logging.getLogger(__name__)


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

    # ------------------------------------------------------------------
    # Async context-manager protocol
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BrowserSession":
        if not PLAYWRIGHT_INSTALLED or async_playwright is None:
            raise RuntimeError(
                "Playwright is not installed in the environment. Please run 'pip install playwright && playwright install chromium' to enable browser automation."
            )
        self._pw = await async_playwright().start()
        log.debug(
            "Launching Chromium headless=%s slow_mo=%d",
            self._config.headless,
            self._config.slow_mo_ms,
        )
        self._browser = await self._pw.chromium.launch(
            headless=self._config.headless,
            slow_mo=self._config.slow_mo_ms,
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )
        if self._config.tracing_enabled:
            await self._context.tracing.start(screenshots=True, snapshots=True)
            log.debug("Tracing started")
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self._stop_tracing()
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        log.debug("BrowserSession closed")

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
