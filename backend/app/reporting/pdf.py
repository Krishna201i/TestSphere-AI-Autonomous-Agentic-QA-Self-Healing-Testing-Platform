"""
TestSphere-AI — A report document printed to PDF.

Uses the engine's guarded browser (its browser slots and outbound-request
guard), so making a PDF never loads anything: the document is self-contained.
"""

from __future__ import annotations


async def html_to_pdf(html: str) -> bytes:
    from engine.browser import BrowserSession
    from engine.schemas import EngineConfig

    async with BrowserSession(EngineConfig(headless=True)) as session:
        page = await session.new_page()
        await page.set_content(html, wait_until="load")
        return await page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
