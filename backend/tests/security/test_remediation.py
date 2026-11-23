"""Tests for security/remediation.py."""

from security.findings import Finding, FindingSource, Severity
from security.remediation import propose

HEADERS = [("Content-Type", "text/html"), ("X-Content-Type-Options", "sniff"), ("Set-Cookie", "sid=SECRET")]


def _finding(check_id: str, component: str = "https://app.test/") -> Finding:
    return Finding(check_id=check_id, source=FindingSource.SECURITY, title=check_id,
                   severity=Severity.LOW, component=component, recommendation="fix it")


def test_missing_header_is_added_with_context_kept() -> None:
    p = propose(_finding("SEC-HDR-REFERRER"), HEADERS)
    assert p.kind == "header"
    assert p.diff[0].kind == "context" and p.diff[0].text == "Content-Type: text/html"
    assert p.diff[-1].kind == "added" and p.diff[-1].text.startswith("Referrer-Policy:")
    assert 'response.headers["Referrer-Policy"]' in p.snippets["FastAPI / Starlette"]


def test_wrong_value_is_replaced() -> None:
    p = propose(_finding("SEC-HDR-XCTO"), HEADERS)
    kinds = [(d.kind, d.text) for d in p.diff]
    assert ("removed", "X-Content-Type-Options: sniff") in kinds
    assert ("added", "X-Content-Type-Options: nosniff") in kinds


def test_cookie_values_never_leak() -> None:
    p = propose(_finding("SEC-COOKIE-FLAGS", "https://app.test/ (cookie: sid)"), HEADERS)
    text = " ".join(d.text for d in p.diff) + " ".join(p.snippets.values())
    assert "SECRET" not in text
    assert p.diff[-1].text == "Set-Cookie: sid=…; Path=/; HttpOnly; Secure; SameSite=Lax"


def test_cookie_on_http_has_no_secure_flag() -> None:
    p = propose(_finding("SEC-COOKIE-FLAGS", "http://127.0.0.1/ (cookie: sid)"), HEADERS)
    assert "Secure" not in p.diff[-1].text


def test_non_header_findings_are_manual() -> None:
    p = propose(_finding("SEC-TRANSPORT-HTTP"), HEADERS)
    assert (p.kind, p.diff, p.summary) == ("manual", [], "fix it")
