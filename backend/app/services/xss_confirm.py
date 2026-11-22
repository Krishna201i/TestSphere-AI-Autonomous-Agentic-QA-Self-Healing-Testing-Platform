"""
TestSphere-AI — Confirming reflected XSS in a real browser.

The active scanner reports a reflected XSS when its marker comes back
unescaped, but a reflection inside a ``<textarea>``, ``<title>`` or comment
never becomes markup.  Like the validators of commercial scanners, a finding
is only *confirmed* when a script in the payload actually runs: the request is
replayed in Chromium and the payload's ``onerror`` sets a flag on ``window``.

The browser is the engine's ``BrowserSession``: the same outbound guard as
test runs (only public addresses on a hosted server) and the same browser
slots.  The payload only sets that flag; it reads and sends nothing.
"""

from __future__ import annotations

import html
import json
import logging
from urllib.parse import urlencode

logger = logging.getLogger("testsphere.security")

_LOAD_TIMEOUT_MS = 15_000
_SETTLE_MS = 300  # onerror fires once the broken image fails to load


async def confirm_in_browser(method: str, url: str, params: dict[str, str], flag: str) -> bool | None:
    """True when the request's payload ran a script, False when it did not,
    None when the page could not be loaded to tell."""
    from engine.browser import BrowserSession
    from engine.schemas import EngineConfig

    try:
        async with BrowserSession(EngineConfig(headless=True)) as session:
            page = await session.new_page()
            if method.upper() == "GET":
                await page.goto(f"{url}?{urlencode(params)}", wait_until="load", timeout=_LOAD_TIMEOUT_MS)
            else:
                # A form post, as a person's browser would send it
                fields = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
                                 for k, v in params.items())
                await page.set_content(f'<form method="post" action="{html.escape(url)}">{fields}</form>')
                async with page.expect_navigation(wait_until="load", timeout=_LOAD_TIMEOUT_MS):
                    await page.evaluate("document.forms[0].submit()")
            await page.wait_for_timeout(_SETTLE_MS)
            return bool(await page.evaluate(f"() => window[{json.dumps(flag)}] === 1"))
    except Exception as exc:  # noqa: BLE001 - unconfirmed is not "safe": the scanner keeps the finding
        logger.info("XSS confirmation for %s could not load the page: %s", url, exc)
        return None
