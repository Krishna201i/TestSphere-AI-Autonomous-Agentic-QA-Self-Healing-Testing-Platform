"""The analysis log states what was measured, never a check that was not run."""

from app.services.url_analyzer import URLAnalyzerService

ARGS = dict(url="https://example.test", title="Shop", latency_ms=120, inputs_count=2, buttons_count=1,
            forms_count=1, overall_score=80, steps_count=4)


def messages(**kw):
    return " | ".join(e["message"] for e in URLAnalyzerService._generate_telemetry_events(**{**ARGS, **kw}))


def test_an_error_status_is_not_reported_as_ok():
    text = messages(status_code=404)
    assert "HTTP 404 Not Found" in text
    assert " OK" not in text


def test_planned_steps_are_not_claimed_as_verified():
    text = messages(status_code=200)
    assert "HTTP 200 OK" in text
    assert "verified cleanly" not in text
    assert "checked against the live page only when the test runs" in text


def test_says_how_the_page_was_read_and_why_nothing_was_planned():
    text = messages(status_code=200, rendered=True, hidden_controls=3, blocked="a CAPTCHA blocks automated submits")
    assert "real browser" in text and "3 control(s) hidden" in text
    assert "Interaction not planned: a CAPTCHA" in text


def test_a_failed_fetch_stops_the_log_there():
    events = URLAnalyzerService._generate_telemetry_events(**ARGS, status_code=0, error="connection refused")
    assert [e["event_type"] for e in events] == ["WORKFLOW_STARTED", "PAGE_FETCH_FAILED"]
