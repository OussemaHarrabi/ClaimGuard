"""Optional OpenTelemetry wiring for ClaimGuard (Phase P1).

WHY THIS EXISTS
---------------
P0 defined the safety contract (:mod:`claimguard.ops.telemetry_policy`) and its
runtime sanitizers (:mod:`claimguard.ops.redaction`): *what* may be emitted. This
module is the thin, optional transport that actually emits spans and metrics —
when, and only when, an operator turns it on.

TWO RULES SHAPE EVERY LINE
--------------------------
*   **Off by default.** With ``CLAIMGUARD_OPS_OTEL_ENABLED`` unset (or falsy) no
    code here imports the SDK, registers a provider, opens a socket or adds
    middleware. Importing this module is free.
*   **Fail-open.** Telemetry is observability, never a dependency of the claim
    flow. A dead collector, a malformed endpoint, a missing package or an export
    error is swallowed and logged at most; no path here may raise into a request.
    Metric labels are funneled through
    :func:`claimguard.ops.redaction.sanitize_metric_labels`, so an unvalidated
    label cannot leave this module.

The OpenTelemetry SDK is imported lazily *inside* the functions, inside
``try/except ImportError``, so importing this module never fails and costs
nothing while telemetry is off.
"""

from __future__ import annotations

import logging
import math
import os
import sys
import threading
from collections.abc import Generator, Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, cast
from urllib.parse import urlparse

from claimguard.config import Settings, get_settings
from claimguard.ops.redaction import sanitize_metric_labels

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.metrics import Counter, Histogram, Meter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import Tracer

logger = logging.getLogger(__name__)

#: Environment switch; truthy values are the explicit ``{1,true,yes,on}`` set.
OTEL_ENABLED_ENV: Final = "CLAIMGUARD_OPS_OTEL_ENABLED"

_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})

#: Exporter timeout in seconds — short so a dead collector cannot stall a flush.
_EXPORT_TIMEOUT_SECONDS: Final = 5.0
#: Force-flush budget on shutdown, in milliseconds (bounded on purpose).
_FLUSH_TIMEOUT_MS: Final = 5000
_METRIC_EXPORT_INTERVAL_MS: Final = 60000
_METRIC_EXPORT_TIMEOUT_MS: Final = 5000

_METER_SCOPE: Final = "claimguard"
_TRACER_SCOPE: Final = "claimguard"
_COUNTER_NAME: Final = "claimguard_http_requests_total"
_HISTOGRAM_NAME: Final = "claimguard_http_request_duration_milliseconds"

#: The bounded domain counters. Each name maps to its single label dimension and
#: the exact allow-list of label values, so a counter can never grow a
#: high-cardinality label even if a caller passes something unexpected. These are
#: deliberately NOT added to the P0 metric-label policy: they are a closed,
#: code-owned set of business outcomes, validated here before they reach the meter.
_CLAIMS_SUBMITTED_COUNTER: Final = "claimguard_claims_submitted_total"
_DECISIONS_COUNTER: Final = "claimguard_decisions_total"
_INTAKE_JOBS_COUNTER: Final = "claimguard_intake_jobs_total"

_DOMAIN_COUNTERS: Final[dict[str, tuple[str, frozenset[str]]]] = {
    _CLAIMS_SUBMITTED_COUNTER: ("outcome", frozenset({"submitted", "duplicate"})),
    _DECISIONS_COUNTER: (
        "action",
        frozenset(
            {
                "confirm_issue",
                "dismiss_with_reason",
                "request_information",
                "mark_corrected_for_recheck",
            }
        ),
    ),
    _INTAKE_JOBS_COUNTER: ("outcome", frozenset({"needs_review", "rejected", "submitted"})),
}


def _empty_domain_counters() -> dict[str, Counter]:
    """A fresh, empty map of domain counter name to instrument."""
    return {}


@dataclass
class _TelemetryState:
    """Process-wide provider and instrument handles; empty until initialized.

    The counter and histogram are created once here rather than per request: an
    OpenTelemetry instrument is a long-lived object, so rebuilding it on every
    request would both waste work and fragment aggregation.
    """

    initialized: bool = False
    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None
    meter: Meter | None = None
    counter: Counter | None = None
    histogram: Histogram | None = None
    domain_counters: dict[str, Counter] = field(default_factory=_empty_domain_counters)


_state = _TelemetryState()
_LOCK = threading.Lock()


class _NullTracer:
    """No-op tracer used only if ``opentelemetry-api`` cannot be imported."""

    def start_as_current_span(
        self, name: str, *args: object, **kwargs: object
    ) -> AbstractContextManager[object]:
        return nullcontext()

    def start_span(self, name: str, *args: object, **kwargs: object) -> object:
        return None


class _NullInstrument:
    """No-op metric instrument used only without ``opentelemetry-api``."""

    def add(self, amount: object, attributes: object | None = None) -> None:
        return None

    def record(self, amount: object, attributes: object | None = None) -> None:
        return None


class _NullMeter:
    """No-op meter used only if ``opentelemetry-api`` cannot be imported."""

    def create_counter(self, name: str, *args: object, **kwargs: object) -> _NullInstrument:
        return _NullInstrument()

    def create_histogram(self, name: str, *args: object, **kwargs: object) -> _NullInstrument:
        return _NullInstrument()


# ---------------------------------------------------------------------------
# Enablement
# ---------------------------------------------------------------------------


def telemetry_enabled(settings: Settings | None = None) -> bool:
    """Return True only for an explicit truthy switch; False by default.

    The raw environment value wins when it is set, so tests and operators get
    the exact ``{1,true,yes,on}`` allow-list rather than pydantic's broader
    boolean coercion; ``settings.ops_otel_enabled`` is the typed fallback.
    """
    raw = os.environ.get(OTEL_ENABLED_ENV)
    if raw is not None:
        return raw.strip().lower() in _TRUTHY
    resolved = settings if settings is not None else _safe_settings()
    return bool(resolved is not None and resolved.ops_otel_enabled)


def telemetry_initialized() -> bool:
    """Return True once providers have been built and registered."""
    return _state.initialized


# ---------------------------------------------------------------------------
# Provider lifecycle
# ---------------------------------------------------------------------------


def init_telemetry(settings: Settings | None = None) -> bool:
    """Build and register the OTel providers when the switch is on; idempotent.

    Returns False when telemetry is disabled or initialization could not
    complete; it never raises (init failure is an observability problem, not a
    request problem).
    """
    with _LOCK:
        if _state.initialized:
            return True
        if not telemetry_enabled(settings):
            return False
        resolved = settings if settings is not None else _safe_settings()
        if resolved is None:
            logger.warning("telemetry: settings unavailable; leaving telemetry disabled")
            return False
        endpoint = resolved.otel_endpoint
        if not _valid_endpoint(endpoint):
            logger.warning(
                "telemetry: malformed OTLP endpoint %r; leaving telemetry disabled", endpoint
            )
            return False
        service_name = resolved.otel_service_name or "claimguard"
        try:
            _build_providers(endpoint, service_name)
        except ImportError:
            logger.warning(
                "telemetry: OpenTelemetry packages unavailable; leaving telemetry disabled"
            )
            return False
        except Exception:  # noqa: BLE001 - initialization must never raise
            logger.warning("telemetry: provider initialization failed; leaving telemetry disabled")
            return False
        _state.initialized = True
        return True


def shutdown_telemetry() -> None:
    """Force-flush within a bounded budget, then shut the providers down.

    Never raises: shutdown runs during teardown, where a telemetry failure must
    not become a process failure.
    """
    with _LOCK:
        tracer_provider = _state.tracer_provider
        meter_provider = _state.meter_provider
        _state.initialized = False
        _state.tracer_provider = None
        _state.meter_provider = None
        _state.meter = None
        _state.counter = None
        _state.histogram = None
        _state.domain_counters = {}
    try:
        if tracer_provider is not None:
            tracer_provider.force_flush(_FLUSH_TIMEOUT_MS)
            tracer_provider.shutdown()
    except Exception:  # noqa: BLE001 - shutdown must never raise
        logger.warning("telemetry: tracer provider shutdown failed; ignoring")
    try:
        if meter_provider is not None:
            meter_provider.force_flush(_FLUSH_TIMEOUT_MS)
            meter_provider.shutdown()
    except Exception:  # noqa: BLE001 - shutdown must never raise
        logger.warning("telemetry: meter provider shutdown failed; ignoring")


def get_tracer(name: str) -> Tracer:
    """Return a tracer from the active provider, or a no-op when disabled."""
    if _state.tracer_provider is not None:
        return _state.tracer_provider.get_tracer(name)
    return _noop_tracer(name)


def get_meter(name: str) -> Meter:
    """Return a meter from the active provider, or a no-op when disabled."""
    if _state.meter_provider is not None:
        return _state.meter_provider.get_meter(name)
    return _noop_meter(name)


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def install_telemetry(app: FastAPI, settings: Settings | None = None) -> bool:
    """Attach telemetry to ``app`` when enabled; return whether anything was added.

    Adds the HTTP metrics middleware and FastAPI instrumentation on top of the
    initialized providers. Every step is guarded so a broken collector can never
    stop the application from starting or serving.
    """
    if not telemetry_enabled(settings):
        return False
    installed = False
    try:
        installed = init_telemetry(settings) or installed
    except Exception:  # noqa: BLE001 - installation must never raise
        logger.warning("telemetry: initialization raised unexpectedly; continuing without it")
    try:
        if not bool(getattr(app.state, "telemetry_installed", False)):
            from claimguard.ops.http_metrics import HttpMetricsMiddleware

            app.add_middleware(HttpMetricsMiddleware)
            app.state.telemetry_installed = True
            installed = True
    except Exception:  # noqa: BLE001 - middleware installation must never raise
        logger.warning("telemetry: HTTP metrics middleware could not be installed")
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        installed = True
    except ImportError:
        logger.warning("telemetry: FastAPI instrumentation unavailable")
    except Exception:  # noqa: BLE001 - instrumentation must never raise
        logger.warning("telemetry: FastAPI instrumentation failed")
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        # Instrument the engine the app already built (its store's), so database
        # time appears as child spans under the request/pipeline spans. Without an
        # engine to hand, patch future engines instead of failing.
        store = getattr(app.state, "store", None)
        engine = getattr(store, "engine", None)
        instrumentor = SQLAlchemyInstrumentor()
        if engine is not None:
            instrumentor.instrument(engine=engine)
        else:
            instrumentor.instrument()
        installed = True
    except ImportError:
        logger.warning("telemetry: SQLAlchemy instrumentation unavailable")
    except Exception:  # noqa: BLE001 - instrumentation must never raise
        logger.warning("telemetry: SQLAlchemy instrumentation failed")
    return installed


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------


def record_http_metric(
    *,
    method: str,
    route_template: str,
    status_class: str,
    duration_ms: float,
    service: str = "claimguard",
    component: str = "api",
) -> None:
    """Record one request counter and duration histogram; fail-open.

    Labels go through the P0 sanitizer, so an invalid or identifier-like label is
    dropped rather than emitted; an empty label set is skipped. Never raises.
    """
    if not _state.initialized or _state.counter is None or _state.histogram is None:
        return
    if not math.isfinite(duration_ms) or duration_ms < 0:
        return
    labels = sanitize_metric_labels(
        {
            "service": service,
            "component": component,
            "route_template": route_template,
            "method": method,
            "status_class": status_class,
        }
    )
    if not labels:
        return
    try:
        _state.counter.add(1, labels)
        _state.histogram.record(duration_ms, labels)
    except Exception:  # noqa: BLE001 - emission must never raise into a request
        logger.warning("telemetry: failed to record HTTP metric; ignoring")


def record_domain_metric(name: str, value: str) -> None:
    """Increment one bounded domain counter; low-cardinality by construction.

    ``name`` is one of :data:`_DOMAIN_COUNTERS`; ``value`` must be in that
    counter's fixed value set or it is dropped. This closes the label space in
    code (the API can only ever emit outcomes/actions the schema itself defines),
    so no identifier or free text can become a label. Never raises.
    """
    if not _state.initialized:
        return
    spec = _DOMAIN_COUNTERS.get(name)
    counter = _state.domain_counters.get(name)
    if spec is None or counter is None or value not in spec[1]:
        return
    try:
        counter.add(1, {spec[0]: value})
    except Exception:  # noqa: BLE001 - emission must never raise into a request
        logger.warning("telemetry: failed to record domain metric; ignoring")


@contextmanager
def span(name: str, attributes: Mapping[str, str] | None = None) -> Generator[None, None, None]:
    """Open one span around a pipeline stage, swallowing any tracing failure.

    Tracing is observability, never a dependency of the claim flow: if the tracer
    cannot be fetched, cannot start a span, or cannot close one, the enclosed
    work still runs and the real exception (if any) still propagates. Attribute
    values are the caller's responsibility and must be policy-safe (route
    template, method, version) — never a claim/member id or free text.
    """
    manager: AbstractContextManager[object] | None = None
    try:
        tracer = get_tracer(_TRACER_SCOPE)
        started = tracer.start_as_current_span(name, attributes=dict(attributes or {}))
        manager = cast("AbstractContextManager[object]", started)
        manager.__enter__()
    except Exception:  # noqa: BLE001 - a tracer fault must not break the stage
        manager = None
    try:
        yield
    finally:
        if manager is not None:
            exc_type, exc, traceback = sys.exc_info()
            try:
                manager.__exit__(exc_type, exc, traceback)
            except Exception:  # noqa: BLE001 - a tracer fault must not break the stage
                logger.warning("telemetry: failed to close span; ignoring")


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _safe_settings() -> Settings | None:
    """Return cached settings, or None if configuration itself is broken."""
    try:
        return get_settings()
    except Exception:  # noqa: BLE001 - a bad config must not break telemetry checks
        return None


def _valid_endpoint(endpoint: str) -> bool:
    """True for an absolute http(s) OTLP base endpoint."""
    parsed = urlparse(endpoint.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _otlp_endpoint(base: str, signal: str) -> str:
    """Build the per-signal OTLP/HTTP path, tolerating an endpoint that already has it."""
    trimmed = base.strip().rstrip("/")
    suffix = f"/v1/{signal}"
    return trimmed if trimmed.endswith(suffix) else trimmed + suffix


def _build_providers(endpoint: str, service_name: str) -> None:
    """Construct, wire and globally register the tracer and meter providers."""
    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({SERVICE_NAME: service_name})

    span_exporter = OTLPSpanExporter(
        endpoint=_otlp_endpoint(endpoint, "traces"),
        timeout=_EXPORT_TIMEOUT_SECONDS,
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    metric_exporter = OTLPMetricExporter(
        endpoint=_otlp_endpoint(endpoint, "metrics"),
        timeout=_EXPORT_TIMEOUT_SECONDS,
    )
    reader = PeriodicExportingMetricReader(
        metric_exporter,
        export_interval_millis=_METRIC_EXPORT_INTERVAL_MS,
        export_timeout_millis=_METRIC_EXPORT_TIMEOUT_MS,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    meter = meter_provider.get_meter(_METER_SCOPE)
    _state.tracer_provider = tracer_provider
    _state.meter_provider = meter_provider
    _state.meter = meter
    _state.counter = meter.create_counter(
        _COUNTER_NAME,
        description="HTTP requests handled, by route template, method and status class.",
        unit="1",
    )
    _state.histogram = meter.create_histogram(
        _HISTOGRAM_NAME,
        description="HTTP request duration in milliseconds.",
        unit="ms",
    )
    _state.domain_counters = {
        name: meter.create_counter(name, description=f"ClaimGuard domain counter {name}.", unit="1")
        for name in _DOMAIN_COUNTERS
    }


def _noop_tracer(name: str) -> Tracer:
    try:
        from opentelemetry.trace import NoOpTracerProvider
    except ImportError:  # pragma: no cover - opentelemetry-api is a hard dependency
        return cast("Tracer", _NullTracer())
    return NoOpTracerProvider().get_tracer(name)


def _noop_meter(name: str) -> Meter:
    try:
        from opentelemetry.metrics import NoOpMeterProvider
    except ImportError:  # pragma: no cover - opentelemetry-api is a hard dependency
        return cast("Meter", _NullMeter())
    return NoOpMeterProvider().get_meter(name)
