"""Technical Reviewer operations surface (Phase P2).

WHY THIS EXISTS
---------------
The reviewer console shows real platform health without asking anyone to open
Grafana, Prometheus or Tempo. This process is the **only** thing that talks to
those systems: the endpoints below are a bounded, read-only projection of their
state, so the browser never holds a telemetry credential and never speaks to a
monitoring backend directly.

THE BOUNDARY THIS MODULE KEEPS
------------------------------
*   **Backend-only telemetry access.** Prometheus and Tempo are reached here,
    server-side, over the same short HTTP clients
    (:mod:`claimguard.ops.sources`). No source credential is accepted or
    forwarded.
*   **No PII, no claim content.** These endpoints expose counts, durations,
    trace identifiers and component states. They never return a claim, a
    patient identifier, reviewer free text or an audit payload.
*   **Audit is business traceability, not telemetry.** ``GET /audit`` reads the
    append-only claimguard audit chain through the existing
    :mod:`claimguard.audit.chain` verifier. It reports only ``intact`` and an
    ``event_count`` — never an event body, hash or actor. The audit ledger lives
    in PostgreSQL and is deliberately separate from the metrics/traces surface.
*   **Fail-open, bounded, never 500.** A source that is down degrades the
    response to a normal ``200`` with the source marked ``unavailable`` and a
    short reason. The one exception is the audit check, which is
    safety-adjacent: when it cannot complete it reports ``intact: false`` — it
    must never imply success it did not verify.

A tiny per-application cache (default 5 s) keeps a page refresh from hammering
the sources; the cache is keyed per endpoint and parameter set and never caches
across applications.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Final, Literal, TypeVar, cast

from fastapi import APIRouter, FastAPI, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from claimguard.audit.chain import AuditEvent, verify_chain
from claimguard.config import get_settings
from claimguard.edu.envelope import RULE_VERSION
from claimguard.edu.policy import RuleDirError
from claimguard.ops.sources import (
    MetricSeries,
    PrometheusSource,
    SourceState,
    SourceStatus,
    SourceUnavailable,
    TempoSource,
    TraceSummary,
)

#: How long a cached operations response stays fresh.
DEFAULT_CACHE_TTL_SECONDS: Final = 5.0

#: The metric window used for the overview's reachability probe, in seconds.
_OVERVIEW_WINDOW_SECONDS: Final = 300

#: The trace page used for the overview's reachability probe.
_OVERVIEW_TRACE_LIMIT: Final = 1

#: The only metric windows the API accepts, and their length in seconds.
Window = Literal["5m", "15m", "1h"]
_WINDOW_SECONDS: Final[dict[str, int]] = {"5m": 300, "15m": 900, "1h": 3600}

#: ``app.state`` attribute names, injectable so tests never touch the network.
_PROMETHEUS_ATTR: Final = "prometheus_source"
_TEMPO_ATTR: Final = "tempo_source"
_CACHE_ATTR: Final = "operations_cache"
_AUDIT_CHECK_ATTR: Final = "audit_check"
_AUDIT_ENGINE_ATTR: Final = "audit_engine"

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Response contracts (frozen)
# ---------------------------------------------------------------------------


class ComponentStatus(BaseModel):
    """One platform component's readiness, as the console lists it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    state: Literal["healthy", "degraded", "unknown"]
    detail: str | None = None


class OperationVersions(BaseModel):
    """The versions the console shows beside the health verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    engine_rule_version: str
    schema_revision: str | None = None
    service_name: str


class NamedSourceStatus(BaseModel):
    """A source status plus the name the overview lists it under.

    ``GET /metrics`` and ``GET /traces`` carry a single anonymous ``source``;
    the overview needs each one identified, so it uses this wrapper. It adds no
    data beyond :class:`~claimguard.ops.sources.SourceStatus`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    state: SourceState
    last_data_at: datetime | None = None
    detail: str | None = None


class OverviewResponse(BaseModel):
    """The one-screen operational summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok", "degraded"]
    checked_at: datetime
    components: list[ComponentStatus]
    sources: list[NamedSourceStatus]
    versions: OperationVersions


class MetricsResponse(BaseModel):
    """One metric window from Prometheus, or an honest degradation of it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: SourceStatus
    window: str
    series: list[MetricSeries]


class TracesResponse(BaseModel):
    """One trace page from Tempo, or an honest degradation of it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: SourceStatus
    traces: list[TraceSummary]


class AuditResponse(BaseModel):
    """Whether the append-only audit chain verified, and how many events it holds.

    ``detail`` is always empty: a failure names no event and leaks no ledger
    content, it only refuses to claim success.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    intact: bool
    checked_at: datetime
    event_count: int
    detail: str | None = None


class AuditStatus(BaseModel):
    """The result of one audit-chain verification (the injectable seam's shape)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intact: bool
    event_count: int


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class OperationsCache:
    """A tiny thread-safe TTL cache for operations responses.

    Serves one application's endpoint calls so a reviewer refreshing a page does
    not re-query Prometheus/Tempo on every request. Values are the frozen
    response models themselves; the cache is bounded by the endpoint+parameters
    keys the routes use.
    """

    def __init__(self, ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS) -> None:
        self._ttl = max(0.0, ttl_seconds)
        self._lock = threading.Lock()
        self._entries: dict[object, tuple[float, object]] = {}

    def get_or_set(self, key: object, producer: Callable[[], T]) -> T:
        """Return the cached value for ``key``, or produce, store and return it."""
        now = time.monotonic()
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None and cached[0] > now:
                return cast(T, cached[1])
        value = producer()
        with self._lock:
            self._entries[key] = (time.monotonic() + self._ttl, value)
        return value


def _cache_for(app: FastAPI) -> OperationsCache:
    """The app's operations cache, created once per application."""
    cache = getattr(app.state, _CACHE_ATTR, None)
    if not isinstance(cache, OperationsCache):
        cache = OperationsCache()
        setattr(app.state, _CACHE_ATTR, cache)
    return cache


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/v1/operations", tags=["operations"])


@router.get("/overview", response_model=OverviewResponse)
def overview(request: Request) -> OverviewResponse:
    """Platform health: components, source reachability and versions."""
    return _cache_for(request.app).get_or_set("overview", lambda: _overview(request.app))


@router.get("/metrics", response_model=MetricsResponse)
def metrics(
    request: Request,
    window: Annotated[Window, Query()] = "15m",
) -> MetricsResponse:
    """The latest samples of the allow-listed HTTP metrics over a bounded window."""
    return _cache_for(request.app).get_or_set(
        ("metrics", window), lambda: _metrics(request.app, window)
    )


@router.get("/traces", response_model=TracesResponse)
def traces(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TracesResponse:
    """A bounded page of recent traces."""
    return _cache_for(request.app).get_or_set(
        ("traces", limit), lambda: _traces(request.app, limit)
    )


@router.get("/audit", response_model=AuditResponse)
def audit(request: Request) -> AuditResponse:
    """Whether the append-only audit chain verifies; never claims unverified success."""
    return _cache_for(request.app).get_or_set("audit", lambda: _audit(request.app))


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _overview(app: FastAPI) -> OverviewResponse:
    """Assemble the overview, degrading any source that cannot answer."""
    database, revision = _database_check(app)
    rules = _rules_check(app)
    sources = [_prometheus_status(app), _tempo_status(app)]
    ready = database.state == "healthy" and rules.state == "healthy"
    sources_healthy = all(source.state is SourceState.HEALTHY for source in sources)
    return OverviewResponse(
        status="ok" if ready and sources_healthy else "degraded",
        checked_at=datetime.now(UTC),
        components=[
            ComponentStatus(name="api", state="healthy", detail=None),
            database,
            rules,
        ],
        sources=sources,
        versions=OperationVersions(
            engine_rule_version=RULE_VERSION,
            schema_revision=revision,
            service_name=_service_name(),
        ),
    )


def _metrics(app: FastAPI, window: Window) -> MetricsResponse:
    """Query Prometheus for ``window``, or return an unavailable source."""
    series: list[MetricSeries] = []
    try:
        series = _prometheus_source(app).query_samples(_WINDOW_SECONDS[window])
    except SourceUnavailable as exc:
        return MetricsResponse(
            source=SourceStatus(state=SourceState.UNAVAILABLE, detail=_short(str(exc))),
            window=window,
            series=[],
        )
    except Exception as exc:  # noqa: BLE001 - fail-open: never 500 an ops endpoint
        return MetricsResponse(
            source=SourceStatus(
                state=SourceState.UNAVAILABLE,
                detail=f"prometheus check failed ({type(exc).__name__})",
            ),
            window=window,
            series=[],
        )
    return MetricsResponse(
        source=SourceStatus(state=SourceState.HEALTHY), window=window, series=series
    )


def _traces(app: FastAPI, limit: int) -> TracesResponse:
    """Query Tempo for ``limit`` traces, or return an unavailable source."""
    traces: list[TraceSummary] = []
    try:
        traces = _tempo_source(app).search_traces(limit)
    except SourceUnavailable as exc:
        return TracesResponse(
            source=SourceStatus(state=SourceState.UNAVAILABLE, detail=_short(str(exc))),
            traces=[],
        )
    except Exception as exc:  # noqa: BLE001 - fail-open: never 500 an ops endpoint
        return TracesResponse(
            source=SourceStatus(
                state=SourceState.UNAVAILABLE,
                detail=f"tempo check failed ({type(exc).__name__})",
            ),
            traces=[],
        )
    return TracesResponse(
        source=SourceStatus(state=SourceState.HEALTHY, last_data_at=_latest(traces)),
        traces=traces,
    )


def _audit(app: FastAPI) -> AuditResponse:
    """Verify the audit chain; a check that cannot complete reports no success."""
    checked_at = datetime.now(UTC)
    try:
        status = _audit_status(app)
    except Exception:  # noqa: BLE001 - safety check fails closed, not open
        return AuditResponse(intact=False, checked_at=checked_at, event_count=0, detail=None)
    return AuditResponse(
        intact=status.intact,
        checked_at=checked_at,
        event_count=status.event_count,
        detail=None,
    )


# ---------------------------------------------------------------------------
# Source probing
# ---------------------------------------------------------------------------


def _prometheus_status(app: FastAPI) -> NamedSourceStatus:
    """Reachability of Prometheus, as a source status (never raises)."""
    try:
        _prometheus_source(app).query_samples(_OVERVIEW_WINDOW_SECONDS)
    except SourceUnavailable as exc:
        return NamedSourceStatus(
            name="prometheus", state=SourceState.UNAVAILABLE, detail=_short(str(exc))
        )
    except Exception as exc:  # noqa: BLE001 - fail-open probe
        return NamedSourceStatus(
            name="prometheus",
            state=SourceState.UNAVAILABLE,
            detail=f"prometheus check failed ({type(exc).__name__})",
        )
    return NamedSourceStatus(name="prometheus", state=SourceState.HEALTHY)


def _tempo_status(app: FastAPI) -> NamedSourceStatus:
    """Reachability of Tempo, as a source status (never raises)."""
    try:
        traces = _tempo_source(app).search_traces(_OVERVIEW_TRACE_LIMIT)
    except SourceUnavailable as exc:
        return NamedSourceStatus(
            name="tempo", state=SourceState.UNAVAILABLE, detail=_short(str(exc))
        )
    except Exception as exc:  # noqa: BLE001 - fail-open probe
        return NamedSourceStatus(
            name="tempo",
            state=SourceState.UNAVAILABLE,
            detail=f"tempo check failed ({type(exc).__name__})",
        )
    return NamedSourceStatus(name="tempo", state=SourceState.HEALTHY, last_data_at=_latest(traces))


def _database_check(app: FastAPI) -> tuple[ComponentStatus, str | None]:
    """The database component, using the same schema-revision probe as ``/v1/health``."""
    store = getattr(app.state, "store", None)
    if store is None:
        return (
            ComponentStatus(
                name="database", state="unknown", detail="no review store is configured"
            ),
            None,
        )
    try:
        revision = store.schema_revision()
    except Exception as exc:  # noqa: BLE001 - readiness reporting must not raise
        return (
            ComponentStatus(
                name="database", state="degraded", detail=f"unreachable ({type(exc).__name__})"
            ),
            None,
        )
    if revision is None:
        return (
            ComponentStatus(
                name="database",
                state="degraded",
                detail="schema missing (run `alembic upgrade head`)",
            ),
            None,
        )
    return ComponentStatus(name="database", state="healthy", detail=None), str(revision)


def _rules_check(app: FastAPI) -> ComponentStatus:
    """The rules component, using the same catalogue load as ``/v1/health``."""
    rules = getattr(app.state, "rules", None)
    if rules is None:
        return ComponentStatus(
            name="rules", state="unknown", detail="no rule catalogue loader is configured"
        )
    try:
        rules.context()
    except RuleDirError:
        return ComponentStatus(name="rules", state="degraded", detail="rule catalogue unavailable")
    except Exception as exc:  # noqa: BLE001 - readiness reporting must not raise
        return ComponentStatus(
            name="rules", state="degraded", detail=f"catalogue failed ({type(exc).__name__})"
        )
    return ComponentStatus(name="rules", state="healthy", detail=None)


def _audit_status(app: FastAPI) -> AuditStatus:
    """Run the audit verification, through an injectable seam when one is installed."""
    checker = getattr(app.state, _AUDIT_CHECK_ATTR, None)
    if callable(checker):
        return cast(Callable[[], AuditStatus], checker)()
    engine = _audit_engine(app)
    with engine.connect() as connection:
        return _verify_ledger(connection)


def _audit_engine(app: FastAPI) -> Engine:
    """The app's audit engine, built with the review store's UTC-pinned factory."""
    engine = getattr(app.state, _AUDIT_ENGINE_ATTR, None)
    if engine is None:
        # Imported lazily: ``claimguard.review`` eagerly loads its app, which
        # imports this module, so a top-level import here would be circular.
        from claimguard.review.store import build_engine

        engine = build_engine()
        setattr(app.state, _AUDIT_ENGINE_ATTR, engine)
    return cast(Engine, engine)


def _verify_ledger(connection: Connection) -> AuditStatus:
    """Read the ledger in chain order and verify it with the shared Python replica.

    The same ``ORDER BY at, event_id`` and the same
    :func:`claimguard.audit.chain.verify_chain` the SQL verifier mirrors. Only the
    verdict and the row count leave this function; no event body does.
    """
    # Imported lazily for the same circular-import reason as ``_audit_engine``.
    from claimguard.review.audit_events import AUDIT_EVENTS

    rows = (
        connection.execute(
            select(AUDIT_EVENTS).order_by(AUDIT_EVENTS.c.at, AUDIT_EVENTS.c.event_id)
        )
        .mappings()
        .all()
    )
    events = [
        AuditEvent(
            at=row["at"],
            claim_ref=row["claim_ref"],
            trace_id=str(row["trace_id"]),
            decision=row["decision"],
            reason_code=row["reason_code"],
            finding_ids=[str(item) for item in (row["finding_ids"] or ())],
            model_version=row["model_version"],
            prev_hash=str(row["prev_hash"]),
            chain_hash=str(row["chain_hash"]),
        )
        for row in rows
    ]
    intact, _ = verify_chain(events)
    return AuditStatus(intact=intact, event_count=len(events))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _prometheus_source(app: FastAPI) -> PrometheusSource:
    """The app's Prometheus client (injected by tests, else from settings)."""
    source = getattr(app.state, _PROMETHEUS_ATTR, None)
    if source is None:
        settings = get_settings()
        source = PrometheusSource(
            base_url=settings.ops_metrics_url,
            timeout_seconds=settings.ops_source_timeout_seconds,
        )
        setattr(app.state, _PROMETHEUS_ATTR, source)
    return cast(PrometheusSource, source)


def _tempo_source(app: FastAPI) -> TempoSource:
    """The app's Tempo client (injected by tests, else from settings)."""
    source = getattr(app.state, _TEMPO_ATTR, None)
    if source is None:
        settings = get_settings()
        source = TempoSource(
            base_url=settings.ops_traces_url,
            timeout_seconds=settings.ops_source_timeout_seconds,
        )
        setattr(app.state, _TEMPO_ATTR, source)
    return cast(TempoSource, source)


def _service_name() -> str:
    """The service name the console shows, from configuration when readable."""
    try:
        return get_settings().otel_service_name or "claimguard"
    except Exception:  # noqa: BLE001 - a broken config must not 500 an ops endpoint
        return "claimguard"


def _latest(traces: list[TraceSummary]) -> datetime | None:
    """The newest trace start time in a page, or None when the page is empty."""
    return max((trace.start_time for trace in traces), default=None)


def _short(detail: str, limit: int = 200) -> str:
    """Collapse a failure reason to one short, log-free line for the console."""
    collapsed = " ".join(detail.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 3] + "..."
