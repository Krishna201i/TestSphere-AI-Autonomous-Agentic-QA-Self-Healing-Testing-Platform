"""Titles and headings the analyzer reads are the ones a visitor sees."""

from types import SimpleNamespace

from backend.services import url_analyzer
from backend.services.url_analyzer import URLAnalyzerService

SHELL = '<!doctype html><html><head><title>CareLink</title></head><body><div id="root"></div><script type="module" src="/app.js"></script></body></html>'
RENDERED = """<html><head><title>Sign in · Patient portal</title></head><body>
<h1>Smarter Insights.<br>Healthier India.</h1><h2>Care<span>Link</span></h2></body></html>"""


async def test_a_client_rendered_page_reports_its_rendered_title_and_headings(monkeypatch):
    async def fetch(url, timeout, headers):
        return SimpleNamespace(status_code=200, url=url, text=SHELL, headers={"content-type": "text/html"}), True

    async def render(cls, url):
        return RENDERED

    monkeypatch.setattr(url_analyzer, "get_verifying_first", fetch)
    monkeypatch.setattr(URLAnalyzerService, "_render_in_browser", classmethod(render))

    result = await URLAnalyzerService.analyze_live_website("https://app.example.com/patient/login")

    # The app's script replaced the shell's title; tests check what the browser shows
    assert result["page_title"] == "Sign in · Patient portal"
    # A <br> is a space; an inline tag joins its text
    assert result["elements_inventory"]["headings"][:2] == ["Smarter Insights. Healthier India.", "CareLink"]


def test_headings_read_a_line_break_as_a_space():
    assert URLAnalyzerService._extract_headings("<h1>One<br/>Two</h1><h2>A<BR >B</h2>") == ["One Two", "A B"]
