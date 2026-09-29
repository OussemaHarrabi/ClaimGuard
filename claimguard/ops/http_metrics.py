"""HTTP metrics middleware for ClaimGuard (Phase P1).

Records one request counter and one duration histogram per HTTP request — but
only through :func:`claimguard.ops.telemetry.record_http_metric`, which is a
no-op unless telemetry is initialized. This middleware never inspects a body,
header or query string, and never lets a recording failure disturb a response:
observability is fail-open, the claim flow is not.

The route dimension is deliberately the routed TEMPLATE (``/v1/runs/{run_id}``)
or the literal ``unmatched`` — never the concrete request path, which would leak
an identifier into a metric label.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from claimguard.ops.telemetry import record_http_metric

logger = logging.getLogger(__name__)

#: Label value used when no route matched; a bounded, policy-safe slug.
UNMATCHED_ROUTE: Final = "unmatched"


def status_class(status_code: int) -> str:
    """Map a concrete HTTP status code to its class label (``200`` -> ``2xx``)."""
    return f"{status_code // 100}xx"


class HttpMetricsMiddleware(BaseHTTPMiddleware):
    """Emit per-request HTTP metrics without ever affecting the response.

    ``recorder`` is injectable so tests can assert what would be recorded without
    a live meter; it defaults to the real, policy-sanitizing recorder.
    """

    def __init__(self, app: ASGIApp, recorder: Callable[..., None] = record_http_metric) -> None:
        super().__init__(app)
        self._recorder = recorder

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            self._emit(request, status_code, _elapsed_ms(started))

    def _emit(self, request: Request, status_code: int, duration_ms: float) -> None:
        """Record via the injected recorder, swallowing any recorder failure."""
        try:
            self._recorder(
                method=request.method,
                route_template=_route_template(request),
                status_class=status_class(status_code),
                duration_ms=duration_ms,
            )
        except Exception:  # noqa: BLE001 - a recorder fault must not break the response
            logger.warning("http metrics recorder failed; telemetry is fail-open")


def _route_template(request: Request) -> str:
    """Return the matched route TEMPLATE, or ``unmatched`` when none matched.

    The route is resolved by the router while ``call_next`` runs and written back
    onto the shared ASGI scope, so reading it after the call yields the template
    (``/v1/runs/{run_id}``) rather than the concrete path.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return UNMATCHED_ROUTE


def _elapsed_ms(started: float) -> float:
    """Milliseconds elapsed since ``started``, clamped at zero."""
    return max(0.0, (time.perf_counter() - started) * 1000.0)
