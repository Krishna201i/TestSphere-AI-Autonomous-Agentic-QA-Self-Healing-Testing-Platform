"""
engine/visual.py
================
Visual regression: how much of the page a test ended on looks different from
the last approved screenshot of that test (its baseline).

The comparison runs in the test's own browser (a blank page drawing both
images on canvases), so no image library is needed.  A pixel counts as
changed when any colour channel differs by more than ``TOLERANCE``, which
ignores anti-aliasing and compression noise.  The result is the share of
changed pixels and a diff image: the new screenshot faded, changed pixels red.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

log = logging.getLogger(__name__)

TOLERANCE = 40  # per channel, out of 255

_COMPARE_JS = """
async ([baseline, current, tolerance]) => {
  const load = (src) => new Promise((ok, fail) => { const i = new Image(); i.onload = () => ok(i); i.onerror = fail; i.src = src; });
  const [a, b] = await Promise.all([load(baseline), load(current)]);
  if (a.width !== b.width || a.height !== b.height) {
    return {ratio: 1, changed: b.width * b.height, total: b.width * b.height, sizeChanged: true,
            baseline: [a.width, a.height], current: [b.width, b.height], diff: null};
  }
  const pixels = (img) => { const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
    const x = c.getContext('2d'); x.drawImage(img, 0, 0); return x.getImageData(0, 0, img.width, img.height); };
  const pa = pixels(a).data, out = pixels(b), pb = out.data;
  let changed = 0;
  for (let i = 0; i < pb.length; i += 4) {
    const d = Math.max(Math.abs(pa[i] - pb[i]), Math.abs(pa[i + 1] - pb[i + 1]), Math.abs(pa[i + 2] - pb[i + 2]));
    if (d > tolerance) { changed++; pb[i] = 230; pb[i + 1] = 30; pb[i + 2] = 30; pb[i + 3] = 255; }
    else { const g = (pb[i] + pb[i + 1] + pb[i + 2]) / 3; pb[i] = pb[i + 1] = pb[i + 2] = 200 + g / 5; }
  }
  const c = document.createElement('canvas'); c.width = b.width; c.height = b.height;
  c.getContext('2d').putImageData(out, 0, 0);
  return {ratio: changed / (b.width * b.height), changed, total: b.width * b.height, sizeChanged: false,
          diff: changed ? c.toDataURL('image/png') : null};
}
"""


def _data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


async def compare(context: Any, baseline: bytes, current: bytes) -> dict[str, Any]:
    """``{"ratio", "changed", "total", "size_changed", "diff_png"}`` for two PNG screenshots."""
    page = await context.new_page()
    try:
        await page.set_content("<!doctype html><title>compare</title>")
        res = await page.evaluate(_COMPARE_JS, [_data_url(baseline), _data_url(current), TOLERANCE])
    finally:
        await page.close()
    diff = res.get("diff")
    return {
        "ratio": round(float(res["ratio"]), 5), "changed": int(res["changed"]), "total": int(res["total"]),
        "size_changed": bool(res["sizeChanged"]),
        "diff_png": base64.b64decode(diff.split(",", 1)[1]) if diff else None,
    }


async def screenshot(page: Any) -> bytes:
    """The visible viewport, settled: same size every run, animations stopped, no caret."""
    from contextlib import suppress

    with suppress(Exception):  # a page that never goes idle is still compared as it is
        await page.wait_for_load_state("networkidle", timeout=3000)
    with suppress(Exception):
        await page.evaluate("document.fonts && document.fonts.ready")
    return await page.screenshot(full_page=False, animations="disabled", caret="hide")
