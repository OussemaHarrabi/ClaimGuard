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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final, Literal, TypeVar, cast

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Engine

from claimguard.audit.chain import GENESIS, AuditEvent, verify_chain
from claimguard.clinic.access import Action, Principal, authorize
from claimguard.config import get_settings
from claimguard.edu.envelope import RULE_VERSION
from claimguard.edu.policy import RuleDirError
from claimguard.ops.sources import (
    MAX_TRACE_SPANS,
    MetricSeries,
    PrometheusSource,
    SourceNotFound,
    SourceState,
    SourceStatus,
    SourceUnavailable,
    TempoSource,
    TraceDetail,
    TraceSpan,
    TraceSummary,
)

#: How long a cached operations response stays fresh.
DEFAULT_CACHE_TTL_SECONDS: Final = 5.0

#: The metric window used for the overview's reachability probe, in seconds.
_OVERVIEW_WINDOW_SECONDS: Final = 300

#: The trace page used for the overview's reachability probe.
_OVERVIEW_TRACE_LIMIT: Final = 1

#: Largest audit-chain page the API accepts.
MAX_AUDIT_CHAIN_LIMIT: Final = 200

#: Default audit-chain page size.
DEFAULT_AUDIT_CHAIN_LIMIT: Final = 50

#: Honest detail for a source that answered but had no data in the window. A
#: reachable source with nothing to show is not a failure, but it must not
#: imply data either: the timestamp stays null and this says why.
_NO_SAMPLES_DETAIL: Final = "reachable; no samples in this window"
_NO_TRACES_DETAIL: Final = "reachable; no traces in this window"

#: The only metric windows the API accepts, and their length in seconds.
Window = Literal["5m", "15m", "1h"]
_WINDOW_SECONDS: Final[dict[str, int]] = {"5m": 300, "15m": 900, "1h": 3600}

#: ``app.state`` attribute names, injectable so tests never touch the network.
_PROMETHEUS_ATTR: Final = "prometheus_source"
_TEMPO_ATTR: Final = "tempo_source"
_CACHE_ATTR: Final = "operations_cache"
_AUDIT_CHECK_ATTR: Final = "audit_check"
_AUDIT_ENGINE_ATTR: Final = "audit_engine"
_AUDIT_CHAIN_ATTR: Final = "audit_chain_reader"

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


class TraceSpanNode(BaseModel):
    """One span as the console's flow view needs it, offsets and depth included.

    ``depth`` and ``start_offset_ms`` are derived server-side so the browser
    never walks the parent chain; ``start_offset_ms`` is relative to the trace
    start and is always ``>= 0``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    span_id: str
    parent_span_id: str | None
    name: str
    service: str
    start_offset_ms: float
    duration_ms: float
    depth: int
    status: Literal["ok", "error"]


class TraceDetailResponse(BaseModel):
    """One trace's span tree, or an honest degradation of it.

    An unavailable source yields the fail-open shape: the source is marked and
    ``spans`` is empty, never a ``500``. An unknown or expired id is a ``404``
    instead — a missing trace is not the same as a dead source.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: SourceStatus
    trace_id: str
    root_name: str
    duration_ms: float
    spans: list[TraceSpanNode]


class AuditChainLink(BaseModel):
    """One audit-ledger link, from the allowed columns only.

    ``sequence`` is the 1-based position in the whole chain (newest equals
    ``total_events``), so the console can render ``n-1 / n / n+1``. ``linked`` is
    whether this event's ``prev_hash`` equals the next-older event's
    ``chain_hash``; the true oldest event links to ``"genesis"``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int
    event_id: str
    at: datetime
    kind: str
    prev_hash: str
    chain_hash: str
    claim_ref: str | None
    trace_id: str
    linked: bool


class AuditChainResponse(BaseModel):
    """The newest slice of the append-only audit hash chain.

    Only opaque refs and hashes leave here; the ledger's decision content is
    never selected. On a database fault this is the fail-open shape: ``intact``
    false, zero events, no links — the reader never 500s.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    intact: bool
    checked_at: datetime
    total_events: int
    links: list[AuditChainLink]


@dataclass(frozen=True)
class AuditChainRow:
    """One ledger row reduced to the fields the chain page may expose."""

    event_id: str
    at: datetime
    kind: str
    prev_hash: str
    chain_hash: str
    claim_ref: str | None
    trace_id: str


@dataclass(frozen=True)
class AuditChainPage:
    """Up to ``limit + 1`` newest rows (the extra verifies the oldest shown)."""

    rows: list[AuditChainRow]
    total_events: int


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


def cache_for(app: FastAPI) -> OperationsCache:
    """The app's operations cache, created once per application."""
    cache = getattr(app.state, _CACHE_ATTR, None)
    if not isinstance(cache, OperationsCache):
        cache = OperationsCache()
        setattr(app.state, _CACHE_ATTR, cache)
    return cache


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def require_operations(request: Request) -> None:
    """Fail closed unless the resolved principal may read operations telemetry.

    UI visibility is never authorization: the routes below are a raw view of
    platform health, so they demand :data:`Action.READ_OPERATIONS` on every
    request. A request with no resolved principal is denied outright rather
    than treated as anonymous-allowed.
    """
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(status_code=403, detail="access denied")
    try:
        authorize(principal, Action.READ_OPERATIONS, tenant_id=principal.tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="access denied") from exc


router = APIRouter(
    prefix="/v1/operations",
    tags=["operations"],
    dependencies=[Depends(require_operations)],
)


@router.get("/overview", response_model=OverviewResponse)
def overview(request: Request) -> OverviewResponse:
    """Platform health: components, source reachability and versions."""
    return cache_for(request.app).get_or_set("overview", lambda: build_overview(request.app))


@router.get("/metrics", response_model=MetricsResponse)
def metrics(
    request: Request,
    window: Annotated[Window, Query()] = "15m",
) -> MetricsResponse:
    """The latest samples of the allow-listed HTTP metrics over a bounded window."""
    return cache_for(request.app).get_or_set(
        ("metrics", window), lambda: build_metrics(request.app, window)
    )


@router.get("/traces", response_model=TracesResponse)
def traces(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TracesResponse:
    """A bounded page of recent traces."""
    return cache_for(request.app).get_or_set(
        ("traces", limit), lambda: build_traces(request.app, limit)
    )


@router.get("/traces/{trace_id}", response_model=TraceDetailResponse)
def trace_detail(request: Request, trace_id: str) -> TraceDetailResponse:
    """One trace's span tree, with server-computed depth and offsets."""
    return cache_for(request.app).get_or_set(
        ("trace", trace_id), lambda: build_trace_detail(request.app, trace_id)
    )


@router.get("/audit", response_model=AuditResponse)
def audit(request: Request) -> AuditResponse:
    """Whether the append-only audit chain verifies; never claims unverified success."""
    return cache_for(request.app).get_or_set("audit", lambda: build_audit(request.app))


@router.get("/audit/chain", response_model=AuditChainResponse)
def audit_chain(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=MAX_AUDIT_CHAIN_LIMIT)] = DEFAULT_AUDIT_CHAIN_LIMIT,
) -> AuditChainResponse:
    """The newest links of the hash chain: opaque refs and hashes only."""
    return cache_for(request.app).get_or_set(
        ("audit-chain", limit), lambda: build_audit_chain(request.app, limit)
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def build_overview(app: FastAPI) -> OverviewResponse:
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


def build_metrics(app: FastAPI, window: Window) -> MetricsResponse:
    """Query Prometheus for ``window``, or return an unavailable source."""
    try:
        samples = _prometheus_source(app).query_samples(_WINDOW_SECONDS[window])
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
        source=SourceStatus(
            state=SourceState.HEALTHY,
            last_data_at=samples.last_sample_at,
            detail=None if samples.series else _NO_SAMPLES_DETAIL,
        ),
        window=window,
        series=samples.series,
    )


def build_traces(app: FastAPI, limit: int) -> TracesResponse:
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
        source=SourceStatus(
            state=SourceState.HEALTHY,
            last_data_at=_latest(traces),
            detail=None if traces else _NO_TRACES_DETAIL,
        ),
        traces=traces,
    )


def build_audit(app: FastAPI) -> AuditResponse:
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


def build_trace_detail(app: FastAPI, trace_id: str) -> TraceDetailResponse:
    """Fetch one trace's spans, or degrade; an unknown id is a ``404``.

    A dead Tempo is fail-open: a normal response with the source marked and an
    empty span list. A trace Tempo says it does not hold (``404``) is *not* a
    degraded source — it is a missing object, so it becomes a ``404`` with a
    clear detail rather than an empty success that would read as "empty trace".
    """
    try:
        detail = _tempo_source(app).get_trace(trace_id)
    except SourceNotFound as exc:
        raise HTTPException(status_code=404, detail=_short(str(exc))) from exc
    except SourceUnavailable as exc:
        return _unavailable_trace(trace_id, _short(str(exc)))
    except Exception as exc:  # noqa: BLE001 - fail-open: never 500 an ops endpoint
        return _unavailable_trace(trace_id, f"tempo check failed ({type(exc).__name__})")
    if not detail.spans:
        raise HTTPException(status_code=404, detail="trace not found or expired")
    root_name, duration_ms, nodes = _trace_nodes(detail)
    return TraceDetailResponse(
        source=SourceStatus(state=SourceState.HEALTHY, last_data_at=None, detail=None),
        trace_id=detail.trace_id,
        root_name=root_name,
        duration_ms=duration_ms,
        spans=nodes,
    )


def build_audit_chain(app: FastAPI, limit: int) -> AuditChainResponse:
    """Read the newest chain links; a database fault degrades, never 500s.

    ``intact`` comes from the same :func:`_audit_status` the audit page uses, so
    the two surfaces never disagree about the verdict. Reading the link rows is a
    separate, bounded query; if it faults the response is the fail-open shape
    (``intact`` as verified, zero events, no links) rather than an error.
    """
    checked_at = datetime.now(UTC)
    try:
        intact = _audit_status(app).intact
    except Exception:  # noqa: BLE001 - a safety check that cannot complete is not a success
        intact = False
    try:
        page = _audit_chain_page(app, limit)
    except Exception:  # noqa: BLE001 - fail-open: the reader must not break the app
        return AuditChainResponse(intact=intact, checked_at=checked_at, total_events=0, links=[])
    return AuditChainResponse(
        intact=intact,
        checked_at=checked_at,
        total_events=page.total_events,
        links=_chain_links(page, limit),
    )


# ---------------------------------------------------------------------------
# Source probing
# ---------------------------------------------------------------------------


def _prometheus_status(app: FastAPI) -> NamedSourceStatus:
    """Reachability of Prometheus, as a source status (never raises).

    A source that answers with samples is healthy and carries the newest sample
    time it reported. A source that answers with no samples is still reachable,
    so it stays healthy with a null ``last_data_at`` and a detail that says so —
    the console must never render a fabricated time.
    """
    try:
        samples = _prometheus_source(app).query_samples(_OVERVIEW_WINDOW_SECONDS)
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
    return NamedSourceStatus(
        name="prometheus",
        state=SourceState.HEALTHY,
        last_data_at=samples.last_sample_at,
        detail=None if samples.series else _NO_SAMPLES_DETAIL,
    )


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
    return NamedSourceStatus(
        name="tempo",
        state=SourceState.HEALTHY,
        last_data_at=_latest(traces),
        detail=None if traces else _NO_TRACES_DETAIL,
    )


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


def _audit_chain_page(app: FastAPI, limit: int) -> AuditChainPage:
    """Read the newest chain links through the injectable seam or the audit engine."""
    reader = getattr(app.state, _AUDIT_CHAIN_ATTR, None)
    if callable(reader):
        return cast(Callable[[int], AuditChainPage], reader)(limit)
    engine = _audit_engine(app)
    with engine.connect() as connection:
        return _read_chain_page(connection, limit)


def _read_chain_page(connection: Connection, limit: int) -> AuditChainPage:
    """Read ``limit + 1`` newest rows, selecting only the exposable columns.

    The extra row is the next-older event: it is used solely to judge whether the
    oldest row shown is linked and is never returned. No forbidden column
    (``decision``, ``reason_code``, ``finding_ids``, ``rule_version``,
    ``model_version``) is selected.
    """
    # Imported lazily for the same circular-import reason as ``_audit_engine``.
    from claimguard.review.audit_events import AUDIT_EVENTS

    total = int(connection.execute(select(func.count()).select_from(AUDIT_EVENTS)).scalar_one())
    rows = (
        connection.execute(
            select(
                AUDIT_EVENTS.c.event_id,
                AUDIT_EVENTS.c.at,
                AUDIT_EVENTS.c.kind,
                AUDIT_EVENTS.c.claim_ref,
                AUDIT_EVENTS.c.trace_id,
                AUDIT_EVENTS.c.prev_hash,
                AUDIT_EVENTS.c.chain_hash,
            )
            .order_by(AUDIT_EVENTS.c.at.desc(), AUDIT_EVENTS.c.event_id.desc())
            .limit(limit + 1)
        )
        .mappings()
        .all()
    )
    return AuditChainPage(
        rows=[
            AuditChainRow(
                event_id=str(row["event_id"]),
                at=row["at"],
                kind=str(row["kind"]),
                prev_hash=str(row["prev_hash"]),
                chain_hash=str(row["chain_hash"]),
                claim_ref=row["claim_ref"],
                trace_id=str(row["trace_id"]),
            )
            for row in rows
        ],
        total_events=total,
    )


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


def _unavailable_trace(trace_id: str, detail: str) -> TraceDetailResponse:
    """The fail-open trace shape: source marked unavailable, no spans."""
    return TraceDetailResponse(
        source=SourceStatus(state=SourceState.UNAVAILABLE, detail=detail),
        trace_id=trace_id,
        root_name="",
        duration_ms=0.0,
        spans=[],
    )


def _trace_nodes(detail: TraceDetail) -> tuple[str, float, list[TraceSpanNode]]:
    """Give every span its depth and its offset from the trace start.

    Spans are ordered by absolute start time and capped at
    :data:`~claimguard.ops.sources.MAX_TRACE_SPANS`; ``trace_start`` is the
    earliest. Depth is walked from the parent map with a visited set, so a
    corrupt parent cycle cannot loop, and a span whose parent is not present is
    treated as a root. Offsets are clamped at ``>= 0``.
    """
    ordered = sorted(detail.spans, key=lambda span: span.start_time)[:MAX_TRACE_SPANS]
    trace_start = ordered[0].start_time
    by_id = {span.span_id: span for span in ordered}

    def depth_of(span: TraceSpan) -> int:
        depth = 0
        seen = {span.span_id}
        current = span
        while current.parent_span_id and current.parent_span_id in by_id:
            parent = by_id[current.parent_span_id]
            if parent.span_id in seen:
                break
            seen.add(parent.span_id)
            depth += 1
            current = parent
        return depth

    roots = [span for span in ordered if depth_of(span) == 0]
    root = roots[0] if roots else ordered[0]
    trace_end = max(span.start_time + timedelta(milliseconds=span.duration_ms) for span in ordered)
    nodes = [
        TraceSpanNode(
            span_id=span.span_id,
            parent_span_id=span.parent_span_id,
            name=span.name,
            service=span.service,
            start_offset_ms=max(
                0.0, round((span.start_time - trace_start).total_seconds() * 1000.0, 3)
            ),
            duration_ms=round(span.duration_ms, 3),
            depth=depth_of(span),
            status=span.status,
        )
        for span in ordered
    ]
    return root.name, round((trace_end - trace_start).total_seconds() * 1000.0, 3), nodes


def _chain_links(page: AuditChainPage, limit: int) -> list[AuditChainLink]:
    """Build the newest-first link list, numbering ``sequence`` down from the total.

    ``linked`` compares a row's ``prev_hash`` with the next-older row's
    ``chain_hash``; the true oldest event (no older row loaded) is linked exactly
    when its ``prev_hash`` is ``"genesis"``. That is honest: a mid-chain row whose
    predecessor was not loaded is verified against the extra row that was.
    """
    links: list[AuditChainLink] = []
    for index, row in enumerate(page.rows[:limit]):
        successor = page.rows[index + 1] if index + 1 < len(page.rows) else None
        linked = (
            row.prev_hash == successor.chain_hash
            if successor is not None
            else row.prev_hash == GENESIS
        )
        links.append(
            AuditChainLink(
                sequence=page.total_events - index,
                event_id=row.event_id,
                at=row.at,
                kind=row.kind,
                prev_hash=row.prev_hash,
                chain_hash=row.chain_hash,
                claim_ref=row.claim_ref,
                trace_id=row.trace_id,
                linked=linked,
            )
        )
    return links
