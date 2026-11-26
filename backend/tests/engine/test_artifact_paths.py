"""Artifact folders stay short whatever the test id (a long URL path passed Windows' path limit)."""

from engine.artifacts import MAX_SEGMENT, safe_segment


def test_long_ids_are_shortened_but_stay_distinct():
    a = "pipe-1-link-catalogue-category-books-historical-fiction_4-index-html"
    b = "pipe-1-link-catalogue-category-books-historical-fiction_4-other-html"
    assert len(safe_segment(a)) <= MAX_SEGMENT and safe_segment(a) != safe_segment(b)
    assert safe_segment(a) == safe_segment(a)  # stable


def test_short_ids_are_unchanged_and_nothing_escapes_its_folder():
    assert safe_segment("smoke") == "smoke"
    assert safe_segment("../../etc") == "etc"
    assert "/" not in safe_segment("a/" * 100)


async def test_sessions_in_a_shared_scope_reuse_one_browser_with_separate_contexts():
    from engine.browser import BrowserSession, shared_browsers
    from engine.schemas import EngineConfig

    async with shared_browsers() as shared:
        async with BrowserSession(EngineConfig(headless=True)) as a:
            page = await a.new_page()
            await page.set_content("<p>a</p>")
            await a._context.add_cookies([{"name": "s", "value": "1", "url": "https://x.example/"}])
            browser = a._browser
        async with BrowserSession(EngineConfig(headless=True)) as b:
            assert b._browser is browser                       # reused
            assert await b._context.cookies() == []            # but nothing carried over
        assert browser.is_connected() and shared.launched == 1
    assert not browser.is_connected()                          # closed with the scope
