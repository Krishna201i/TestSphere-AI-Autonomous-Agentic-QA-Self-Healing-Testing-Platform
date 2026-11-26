"""
engine/artifacts.py
===================
Write test artifacts (screenshots, DOM snapshots) to a structured directory.

Layout::

    {artifacts_dir}/
      {test_id}/
        {step_id}/
          screenshot.png
          dom.html

All functions are safe to call even when the page is in a broken state —
errors are caught and logged rather than propagated, so a failed artifact
write never masks the original test failure.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from playwright.async_api import Page

log = logging.getLogger(__name__)


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


# A test id can be a long URL path; with the folders around it that passes
# Windows' 260-character path limit (and Linux's 255-character names)
MAX_SEGMENT = 32


def safe_segment(value: str) -> str:
    """*value* as one short path segment that stays inside its parent
    directory.  A long value keeps its start and gets a hash of the whole,
    so two long ids that share a start stay apart."""
    clean = _UNSAFE.sub("_", str(value)).strip("._") or "_"
    if len(clean) <= MAX_SEGMENT:
        return clean
    digest = hashlib.sha256(str(value).encode()).hexdigest()[:10]
    return f"{clean[:MAX_SEGMENT - 11].rstrip('._')}-{digest}"


def _step_dir(base_dir: str, test_id: str, step_id: str) -> Path:
    """Return (and create) the artifact directory for one step."""
    p = Path(base_dir) / safe_segment(test_id) / safe_segment(step_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


async def write_screenshot(
    page: Page,
    test_id: str,
    step_id: str,
    base_dir: str,
) -> str | None:
    """
    Capture a full-page PNG screenshot and write it to the step artifact dir.

    Returns the absolute path string on success, or ``None`` if capture fails.
    """
    dest = _step_dir(base_dir, test_id, step_id) / "screenshot.png"
    try:
        await page.screenshot(path=str(dest), full_page=True)
        log.debug("Screenshot written: %s", dest)
        return str(dest.resolve())
    except Exception as exc:  # noqa: BLE001 - pragma: no cover
        log.warning("Screenshot capture failed for %s/%s: %s", test_id, step_id, exc)
        return None


async def write_dom_snapshot(
    page: Page,
    test_id: str,
    step_id: str,
    base_dir: str,
) -> str | None:
    """
    Capture the current page HTML and write it to the step artifact dir.

    Returns the absolute path string on success, or ``None`` if capture fails.
    """
    dest = _step_dir(base_dir, test_id, step_id) / "dom.html"
    try:
        html = await page.content()
        dest.write_text(html, encoding="utf-8")
        log.debug("DOM snapshot written: %s", dest)
        return str(dest.resolve())
    except Exception as exc:  # noqa: BLE001 - pragma: no cover
        log.warning("DOM snapshot failed for %s/%s: %s", test_id, step_id, exc)
        return None
