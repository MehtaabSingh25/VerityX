
"""Prometheus metrics for the VerityX API."""

from time import perf_counter

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    REGISTRY,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


def _get_or_create_metric(metric_type, name, documentation, labels=()):
    """Reuse an existing metric if the module is imported more than once."""
    existing = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
    if existing is not None:
        return existing
    return metric_type(name, documentation, labels)


HTTP_REQUESTS = _get_or_create_metric(
    Counter,
    "verityx_http_requests",
    "Total HTTP requests handled by the API.",
    ("method", "route", "status"),
)

HTTP_REQUEST_DURATION = _get_or_create_metric(
    Histogram,
    "verityx_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
)

HTTP_REQUESTS_IN_PROGRESS = _get_or_create_metric(
    Gauge,
    "verityx_http_requests_in_progress",
    "HTTP requests currently being handled.",
)


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        started = perf_counter()
        status = "500"
        HTTP_REQUESTS_IN_PROGRESS.inc()

        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")

            HTTP_REQUESTS.labels(method, route_path, status).inc()
            HTTP_REQUEST_DURATION.labels(method, route_path).observe(
                perf_counter() - started
            )
            HTTP_REQUESTS_IN_PROGRESS.dec()


def install_metrics(app) -> None:
    """Enable Prometheus request metrics and the scrape endpoint."""
    app.add_middleware(PrometheusMetricsMiddleware)

    async def metrics_endpoint() -> Response:
        return Response(
            content=generate_latest(REGISTRY),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )

    app.add_api_route(
        "/metrics",
        metrics_endpoint,
        methods=["GET"],
        include_in_schema=False,
    )
