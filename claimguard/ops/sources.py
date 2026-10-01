"""Read-only clients for the operations console's data sources (Phase P2).

BOUNDARY
--------
The Technical Reviewer never reaches Prometheus, Tempo or Grafana directly. This
process is the only client: it queries those systems over HTTP and exposes a
bounded, read-only projection of what they hold. Nothing here writes, mutates or
configures a source, and nothing here accepts a credential — every client sends
no ``Authorization`` header, no API token and no cookie, and logs no response
body. The clients carry no PII surface of their own: they forward only metric
names from an allow-list and a numeric limit.

FAILURE DISCIPLINE
------------------
A source that times out, answers a non-2xx status or returns something that is
not the documented JSON shape raises :class:`SourceUnavailable`. This module does
**not** swallow that: the HTTP layer above decides how to degrade. Keeping the
failure explicit is what lets the API mark a source ``unavailable`` instead of
silently rendering an empty page that looks like "healthy, no data".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Any, Final, Literal, cast

import httpx
from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class SourceState(StrEnum):
    """How a telemetry source looks right now.

    A ``str`` enum, so the value serialises to its bare name (``"healthy"``) on
    the wire while staying comparable in code.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class SourceStatus(BaseModel):
    """One source's state, when it last produced data, and a short reason."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: SourceState
    last_data_at: datetime | None = None
    detail: str | None = None


class MetricSeries(BaseModel):
    """One metric sample: its name, its low-cardinality labels, its value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    labels: dict[str, str]
    value: float


@dataclass(frozen=True)
class PrometheusSamples:
    """The latest samples plus the newest sample time actually observed.

    ``last_sample_at`` is the timestamp Prometheus attached to the newest sample
    it returned, or ``None`` when the source answered but no returned sample
    carried a usable timestamp. It is never invented: an absent or malformed
    timestamp stays absent, so the console can tell "reachable, no data" apart
    from "data seen at ...".
    """

    series: list[MetricSeries]
    last_sample_at: datetime | None


class TraceSummary(BaseModel):
    """One trace search hit, the shape the operations console renders."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str
    root_name: str
    service: str
    start_time: datetime
    duration_ms: float


class TraceSpan(BaseModel):
    """One span of a fetched trace, with its real start time and outcome.

    ``start_time`` is kept absolute here so the HTTP layer can order spans and
    derive each one's offset from the trace start; ``depth`` and the relative
    offset are presentation, computed in :mod:`claimguard.ops.operations`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    span_id: str
    parent_span_id: str | None
    name: str
    service: str
    start_time: datetime
    duration_ms: float
    status: Literal["ok", "error"]


class TraceDetail(BaseModel):
    """Every span of one trace, in start-time order (the source's raw view)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str
    spans: list[TraceSpan]


class SourceUnavailable(RuntimeError):  # noqa: N818 - the name is part of the P2 contract
    """A source could not answer: timeout, non-2xx status or unparsable body."""


class SourceNotFound(SourceUnavailable):
    """The source answered, but holds no object for the requested id.

    A subclass of :class:`SourceUnavailable` so every existing caller that
    degrades on a missing source keeps doing so; the HTTP layer distinguishes it
    to answer ``404`` for an unknown/expired trace instead of ``200``.
    """


# ---------------------------------------------------------------------------
# Allow-listed queries
# ---------------------------------------------------------------------------

#: The only metric names the backend will ever query. All are low-cardinality
#: instruments emitted by this service: the two HTTP instruments, plus the four
#: bounded domain counters whose sole label dimension is a closed set of
#: outcomes/actions (see :mod:`claimguard.ops.telemetry`). None carries an
#: identifier, and the HTTP label policy (:mod:`claimguard.ops.telemetry_policy`)
#: already bounds their dimensions.
DEFAULT_METRIC_NAMES: Final[tuple[str, ...]] = (
    "claimguard_http_requests_total",
    "claimguard_http_request_duration_milliseconds_count",
    "claimguard_claims_submitted_total",
    "claimguard_decisions_total",
    "claimguard_intake_jobs_total",
    "claimguard_assistant_turns_total",
)

#: Hard allow-list. A metric name not in this set is refused at construction, so
#: no caller can interpolate an arbitrary string into PromQL.
ALLOWED_METRIC_NAMES: Final[frozenset[str]] = frozenset(DEFAULT_METRIC_NAMES)

#: Largest window a caller may request, in seconds (one hour).
MAX_WINDOW_SECONDS: Final = 3600

#: Largest trace page the API will request.
MAX_TRACE_LIMIT: Final = 100

#: Largest number of spans one fetched trace may return, so a pathological
#: trace cannot turn the detail payload into an unbounded response.
MAX_TRACE_SPANS: Final = 200

#: A trace id is an opaque hex token; pinning the alphabet keeps a caller from
#: steering the request path (no ``/``, ``.`` or ``%`` can appear).
_TRACE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-fA-F]{1,64}$")


def _positive_int(value: object, *, name: str, maximum: int) -> int:
    """Return ``value`` clamped to ``maximum``, or raise on a non-positive int."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return min(value, maximum)


def _as_object(value: object) -> dict[str, Any] | None:
    """Return ``value`` as a string-keyed object, or None when it is not one."""
    if not isinstance(value, dict):
        return None
    return cast(dict[str, Any], value)


class _JsonSource:
    """Shared HTTP plumbing: no credentials, no body logging, typed failures."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )

    def _get_json(
        self,
        path: str,
        params: dict[str, str | int],
        *,
        source: str,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """GET ``path`` and decode JSON, mapping every failure to :class:`SourceUnavailable`.

        A ``404`` is raised as :class:`SourceNotFound` so the HTTP layer can tell
        "this object does not exist" from "this source is down". No request or
        response body is ever logged; the raised message names the failure
        category and, for an HTTP error, the status code only.
        """
        try:
            response = self._client.get(path, params=params, headers=headers)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise SourceUnavailable(f"{source} timed out") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == HTTPStatus.NOT_FOUND:
                raise SourceNotFound(f"{source} has no object for this id") from exc
            raise SourceUnavailable(f"{source} returned HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"{source} is unreachable ({type(exc).__name__})") from exc
        try:
            return response.json()
        except ValueError as exc:
            raise SourceUnavailable(f"{source} returned a non-JSON body") from exc


class PrometheusSource(_JsonSource):
    """Prometheus HTTP API client, restricted to the metric allow-list.

    ``query_samples`` runs one instant query per allow-listed metric name, using
    ``last_over_time(<name>[<window>s])`` so ``window_seconds`` bounds the sample
    the console sees without ever interpolating a caller-supplied string into
    PromQL. The only variable parts of a query are an allow-listed metric name and
    an integer.
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 2.0,
        metric_names: tuple[str, ...] = DEFAULT_METRIC_NAMES,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(base_url, timeout_seconds, transport)
        rejected = sorted(name for name in metric_names if name not in ALLOWED_METRIC_NAMES)
        if rejected:
            raise ValueError(
                f"metric names are not allow-listed and will not be queried: {rejected}"
            )
        self._metric_names = tuple(metric_names)

    def query_samples(self, window_seconds: int) -> PrometheusSamples:
        """Return the latest samples and the newest real sample timestamp observed.

        Each Prometheus sample carries its own timestamp alongside its value; the
        newest of them across every allow-listed metric is surfaced as
        :attr:`PrometheusSamples.last_sample_at`, so a healthy source can report
        when data was actually seen instead of an empty placeholder.
        """
        seconds = _positive_int(window_seconds, name="window_seconds", maximum=MAX_WINDOW_SECONDS)
        series: list[MetricSeries] = []
        last_sample_at: datetime | None = None
        for name in self._metric_names:
            query = f"last_over_time({name}[{seconds}s])"
            payload = self._get_json("/api/v1/query", {"query": query}, source="prometheus")
            try:
                parsed = _parse_prometheus(payload, name)
            except SourceUnavailable:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise SourceUnavailable("prometheus returned an unparsable sample") from exc
            series.extend(parsed.series)
            newest = parsed.last_sample_at
            if newest is not None:
                last_sample_at = newest if last_sample_at is None else max(last_sample_at, newest)
        return PrometheusSamples(series=series, last_sample_at=last_sample_at)


class TempoSource(_JsonSource):
    """Tempo HTTP API client for recent trace search hits."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 2.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(base_url, timeout_seconds, transport)

    def search_traces(self, limit: int) -> list[TraceSummary]:
        """Return up to ``limit`` recent traces, newest first as Tempo returns them."""
        bounded = _positive_int(limit, name="limit", maximum=MAX_TRACE_LIMIT)
        payload = self._get_json("/api/search", {"limit": bounded}, source="tempo")
        try:
            return _parse_tempo(payload)
        except SourceUnavailable:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceUnavailable("tempo returned an unparsable trace page") from exc

    def get_trace(self, trace_id: str) -> TraceDetail:
        """Return every span of one trace, ordered by start time and capped.

        Tempo's v1 trace endpoint answers protobuf by default, so the request
        asks for JSON explicitly. An unknown or expired id is a ``404``, which
        surfaces as :class:`SourceNotFound` (a :class:`SourceUnavailable`) so the
        API can answer ``404`` rather than a misleading empty success. A malformed
        id never reaches the network.
        """
        if _TRACE_ID_RE.fullmatch(trace_id) is None:
            raise SourceNotFound("tempo trace id is not a valid hex id")
        payload = self._get_json(
            f"/api/traces/{trace_id}",
            {},
            source="tempo",
            headers={"Accept": "application/json"},
        )
        try:
            detail = _parse_tempo_trace(payload, trace_id)
        except SourceUnavailable:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceUnavailable("tempo returned an unparsable trace") from exc
        ordered = sorted(detail.spans, key=lambda span: span.start_time)
        return TraceDetail(trace_id=trace_id, spans=ordered[:MAX_TRACE_SPANS])


# ---------------------------------------------------------------------------
# Parsing (the two documented JSON shapes)
# ---------------------------------------------------------------------------


def _parse_prometheus(payload: Any, fallback_name: str) -> PrometheusSamples:
    """Parse a Prometheus ``/api/v1/query`` vector response into samples.

    Each ``value`` pair is ``[<unix seconds>, "<value>"]``; the newest usable
    timestamp becomes :attr:`PrometheusSamples.last_sample_at`. A malformed or
    missing timestamp is ignored rather than fabricated, while an unparsable
    metric or value still raises :class:`SourceUnavailable`.
    """
    root = _as_object(payload)
    if root is None:
        raise SourceUnavailable("prometheus returned a non-object payload")
    data = _as_object(root.get("data"))
    if data is None:
        raise SourceUnavailable("prometheus response has no data object")
    result = data.get("result")
    if not isinstance(result, list):
        raise SourceUnavailable("prometheus response has no result list")
    series: list[MetricSeries] = []
    last_sample_at: datetime | None = None
    for item in cast("list[Any]", result):
        entry = _as_object(item)
        if entry is None:
            raise SourceUnavailable("prometheus returned a malformed series")
        metric = _as_object(entry.get("metric"))
        if metric is None:
            raise SourceUnavailable("prometheus series has no metric labels")
        raw_sample = entry.get("value")
        if not isinstance(raw_sample, (list, tuple)):
            raise SourceUnavailable("prometheus series has no sample value")
        sample = cast("list[Any]", raw_sample)
        if len(sample) != 2:
            raise SourceUnavailable("prometheus series has no sample value")
        name = metric.get("__name__", fallback_name)
        labels = {str(key): str(value) for key, value in metric.items() if key != "__name__"}
        series.append(MetricSeries(name=str(name), labels=labels, value=float(sample[1])))
        observed = _sample_time(sample[0])
        if observed is not None and (last_sample_at is None or observed > last_sample_at):
            last_sample_at = observed
    return PrometheusSamples(series=series, last_sample_at=last_sample_at)


def _sample_time(raw: object) -> datetime | None:
    """One Prometheus sample's unix-seconds timestamp, or None when unusable.

    Prometheus encodes the timestamp as a JSON number of seconds. A missing,
    boolean or non-numeric timestamp returns ``None`` so it is never mistaken
    for a real observation time.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(raw), tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _parse_tempo(payload: Any) -> list[TraceSummary]:
    """Parse a Tempo ``/api/search`` response into trace summaries."""
    root = _as_object(payload)
    if root is None:
        raise SourceUnavailable("tempo returned a non-object payload")
    traces = root.get("traces")
    if not isinstance(traces, list):
        raise SourceUnavailable("tempo response has no traces list")
    summaries: list[TraceSummary] = []
    for item in cast("list[Any]", traces):
        entry = _as_object(item)
        if entry is None:
            raise SourceUnavailable("tempo returned a malformed trace")
        summaries.append(
            TraceSummary(
                trace_id=str(entry.get("traceID") or entry.get("traceId") or ""),
                root_name=str(entry.get("rootTraceName") or entry.get("rootName") or ""),
                service=str(entry.get("rootServiceName") or entry.get("service") or ""),
                start_time=_tempo_start_time(entry),
                duration_ms=float(entry.get("durationMs") or 0.0),
            )
        )
    return summaries


def _tempo_start_time(item: dict[str, Any]) -> datetime:
    """Read a Tempo trace's start time from its nanosecond or ISO field."""
    nano = item.get("startTimeUnixNano")
    if nano is not None:
        return datetime.fromtimestamp(int(nano) / 1_000_000_000, tz=UTC)
    raw = item.get("startTime")
    if isinstance(raw, str) and raw:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    raise SourceUnavailable("tempo trace has no start time")


def _parse_tempo_trace(payload: Any, trace_id: str) -> TraceDetail:
    """Parse a Tempo ``/api/traces/{id}`` OTLP JSON body into a trace.

    Tempo renders the OTLP ``TraceData`` message; depending on version it nests
    the resource groups under ``batches`` or ``resourceSpans``. Both are read, and
    within a group both the current ``scopeSpans`` and the older
    ``instrumentationLibrarySpans`` key are accepted. A span missing a usable
    start time is skipped rather than aborting the whole trace.
    """
    root = _as_object(payload)
    if root is None:
        raise SourceUnavailable("tempo returned a non-object payload")
    groups = root.get("batches")
    if not isinstance(groups, list):
        groups = root.get("resourceSpans")
    if not isinstance(groups, list):
        raise SourceUnavailable("tempo trace has no resource groups")
    spans: list[TraceSpan] = []
    for group in cast("list[Any]", groups):
        entry = _as_object(group)
        if entry is None:
            continue
        service = _tempo_service_name(entry)
        for raw_span in _tempo_group_spans(entry):
            parsed = _parse_tempo_span(raw_span, service)
            if parsed is not None:
                spans.append(parsed)
    return TraceDetail(trace_id=trace_id, spans=spans)


def _tempo_group_spans(entry: dict[str, Any]) -> list[Any]:
    """The raw span entries of one resource group, across Tempo/OTLP shapes."""
    scopes = entry.get("scopeSpans")
    if not isinstance(scopes, list):
        scopes = entry.get("instrumentationLibrarySpans")
    if not isinstance(scopes, list):
        return []
    collected: list[Any] = []
    for scope in cast("list[Any]", scopes):
        scope_entry = _as_object(scope)
        if scope_entry is None:
            continue
        scoped = scope_entry.get("spans")
        if isinstance(scoped, list):
            collected.extend(cast("list[Any]", scoped))
    return collected


def _tempo_service_name(entry: dict[str, Any]) -> str:
    """The ``service.name`` resource attribute of a group, or ``"unknown"``."""
    resource = _as_object(entry.get("resource"))
    if resource is None:
        return "unknown"
    attributes = resource.get("attributes")
    if not isinstance(attributes, list):
        return "unknown"
    for attribute in cast("list[Any]", attributes):
        attr = _as_object(attribute)
        if attr is None or attr.get("key") != "service.name":
            continue
        value = _as_object(attr.get("value"))
        if value is None:
            continue
        name = value.get("stringValue")
        if isinstance(name, str) and name:
            return name
    return "unknown"


def _parse_tempo_span(raw: Any, service: str) -> TraceSpan | None:
    """Parse one OTLP span; ``None`` when it carries no usable start time."""
    entry = _as_object(raw)
    if entry is None:
        return None
    start = _tempo_nano_time(entry.get("startTimeUnixNano"))
    if start is None:
        return None
    end = _tempo_nano_time(entry.get("endTimeUnixNano"))
    duration_ms = 0.0 if end is None else max(0.0, (end - start).total_seconds() * 1000.0)
    parent = entry.get("parentSpanId")
    parent_span_id = str(parent) if parent else None
    return TraceSpan(
        span_id=str(entry.get("spanId") or ""),
        parent_span_id=parent_span_id,
        name=str(entry.get("name") or ""),
        service=service,
        start_time=start,
        duration_ms=duration_ms,
        status=_tempo_span_status(entry),
    )


def _tempo_nano_time(raw: Any) -> datetime | None:
    """An OTLP nanosecond timestamp (string or number) as UTC, or ``None``."""
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw) / 1_000_000_000, tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _tempo_span_status(entry: dict[str, Any]) -> Literal["ok", "error"]:
    """Map an OTLP span status to ``"error"`` only for an explicit error code.

    OTLP encodes the status enum as ``2``/``STATUS_CODE_ERROR`` (and its shorthand
    ``ERROR``); unset and OK both render as ``"ok"`` here.
    """
    status = _as_object(entry.get("status"))
    if status is None:
        return "ok"
    code = status.get("code")
    if code in (2, "2", "STATUS_CODE_ERROR", "ERROR", "error"):
        return "error"
    return "ok"
