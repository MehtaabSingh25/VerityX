import json

from fastapi.testclient import TestClient

from app.core.observability import JsonFormatter
from app.main import app


def test_json_formatter_includes_standard_and_extra_fields():
    import logging

    record = logging.LogRecord(
        name="verityx.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    record.event = "test_event"
    record.request_id = "request-123"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "verityx.test"
    assert payload["message"] == "request completed"
    assert payload["event"] == "test_event"
    assert payload["request_id"] == "request-123"
    assert payload["timestamp"].endswith("+00:00")


def test_metrics_endpoint_exposes_prometheus_metrics():
    client = TestClient(app)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "verityx_http_requests_total" in response.text
    assert "verityx_http_request_duration_seconds" in response.text
