"""Request ids, the access log, JSON log lines and optional error reporting."""

import json
import logging

from fastapi.testclient import TestClient

from backend.main import app
from backend.observability import JsonFormatter, init_error_reporting, request_id_var


def test_every_response_carries_a_request_id():
    client = TestClient(app)
    generated = client.get("/api/health").headers["x-request-id"]
    assert len(generated) == 16
    assert client.get("/api/health", headers={"X-Request-ID": "trace-12345678"}).headers["x-request-id"] == "trace-12345678"
    # a malformed incoming id (log injection) is replaced, not echoed
    assert client.get("/api/health", headers={"X-Request-ID": "bad\nid"}).headers["x-request-id"] != "bad\nid"


def test_api_requests_are_logged_with_status_and_duration(caplog):
    with caplog.at_level(logging.INFO, logger="testsphere.access"):
        resp = TestClient(app).get("/api/projects/999")
    line = next(r for r in caplog.records if r.name == "testsphere.access")
    assert line.levelno == logging.WARNING  # 4xx
    assert (line.method, line.path, line.status) == ("GET", "/api/projects/999", 404)
    assert line.duration_ms >= 0
    assert line.request_id == resp.headers["x-request-id"]


def test_json_lines_include_the_request_id_and_extras():
    token = request_id_var.set("req-abcdef12")
    try:
        record = logging.LogRecord("testsphere.test", logging.INFO, __file__, 1, "run %s started", (7,), None)
        record.request_id = request_id_var.get()
        record.run_id = 7
        entry = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert entry["message"] == "run 7 started"
    assert entry["level"] == "INFO" and entry["logger"] == "testsphere.test"
    assert entry["request_id"] == "req-abcdef12" and entry["run_id"] == 7


def test_error_reporting_is_off_without_a_dsn():
    assert init_error_reporting("", "test", None) is False
