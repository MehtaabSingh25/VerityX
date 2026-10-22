"""Structured logging and Prometheus metrics for the VerityX API process."""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from prometheus_client import Counter, Histogram, CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


_RESERVED_LOG_RECORD_KEYS = set(logging.makeLogRecord({}).__dict__) | {
    "message", "asctime", "color_message"
}


class JsonFormatter(logging.Formatter):
    """Serialize log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_RECORD_KEYS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging() -> None:
    """Install a single JSON stream handler without duplicating handlers."""
    root = logging.getLogger()
    if any(getattr(handler, "_verityx_json_handler", False) for handler in root.handlers):
        root.setLevel(logging.INFO)
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler._verityx_json_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(logging.INFO)


HTTP_REQUESTS = Counter(
    "verityx_http_requests_total",
    "HTTP requests handled by the VerityX API process.",
    ("method", "route", "status_code"),
)
HTTP_REQUEST_DURATION = Histogram(
    "verityx_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
)
ANALYSIS_JOBS_SUBMITTED = Counter(
    "verityx_analysis_jobs_submitted_total",
    "Analysis jobs accepted for queueing by the API process.",
    ("analysis_type",),
)
ANALYSIS_JOB_ENQUEUE_FAILURES = Counter(
    "verityx_analysis_job_enqueue_failures_total",
    "Analysis jobs that the API could not enqueue.",
    ("analysis_type",),
)


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    """Log request completion and record bounded-cardinality HTTP metrics."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        started = time.perf_counter()
        status_code = 500
        response: Response | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = time.perf_counter() - started
            route_object = request.scope.get("route")
            route = getattr(route_object, "path", "unmatched")
            method = request.method
            HTTP_REQUESTS.labels(method, route, str(status_code)).inc()
            HTTP_REQUEST_DURATION.labels(method, route).observe(duration)
            logging.getLogger("verityx.http").info(
                "http_request_completed",
                extra={
                    "event": "http_request_completed",
                    "request_id": request_id,
                    "method": method,
                    "route": route,
                    "status_code": status_code,
                    "duration_ms": round(duration * 1000, 2),
                },
            )


def render_metrics() -> tuple[bytes, str]:
    """Return Prometheus exposition bytes and their content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
