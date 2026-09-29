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

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, cast

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


class TraceSummary(BaseModel):
    """One trace search hit, the shape the operations console renders."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str
    root_name: str
    service: str
    start_time: datetime
    duration_ms: float


class SourceUnavailable(RuntimeError):  # noqa: N818 - the name is part of the P2 contract
    """A source could not answer: timeout, non-2xx status or unparsable body."""


# ---------------------------------------------------------------------------
# Allow-listed queries
# ---------------------------------------------------------------------------

#: The only metric names the backend will ever query. Both are low-cardinality
#: HTTP instruments emitted by this service; the label policy
#: (:mod:`claimguard.ops.telemetry_policy`) already bounds their dimensions.
DEFAULT_METRIC_NAMES: Final[tuple[str, ...]] = (
    "claimguard_http_requests_total",
    "claimguard_http_request_duration_milliseconds_count",
)

#: Hard allow-list. A metric name not in this set is refused at construction, so
#: no caller can interpolate an arbitrary string into PromQL.
ALLOWED_METRIC_NAMES: Final[frozenset[str]] = frozenset(DEFAULT_METRIC_NAMES)

#: Largest window a caller may request, in seconds (one hour).
MAX_WINDOW_SECONDS: Final = 3600

#: Largest trace page the API will request.
MAX_TRACE_LIMIT: Final = 100


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

    def _get_json(self, path: str, params: dict[str, str | int], *, source: str) -> Any:
        """GET ``path`` and decode JSON, mapping every failure to :class:`SourceUnavailable`.

        No request or response body is ever logged; the raised message names the
        failure category and, for an HTTP error, the status code only.
        """
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise SourceUnavailable(f"{source} timed out") from exc
        except httpx.HTTPStatusError as exc:
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

    def query_samples(self, window_seconds: int) -> list[MetricSeries]:
        """Return the latest sample of every allow-listed metric within ``window_seconds``."""
        seconds = _positive_int(window_seconds, name="window_seconds", maximum=MAX_WINDOW_SECONDS)
        series: list[MetricSeries] = []
        for name in self._metric_names:
            query = f"last_over_time({name}[{seconds}s])"
            payload = self._get_json("/api/v1/query", {"query": query}, source="prometheus")
            try:
                series.extend(_parse_prometheus(payload, name))
            except SourceUnavailable:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise SourceUnavailable("prometheus returned an unparsable sample") from exc
        return series


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


# ---------------------------------------------------------------------------
# Parsing (the two documented JSON shapes)
# ---------------------------------------------------------------------------


def _parse_prometheus(payload: Any, fallback_name: str) -> list[MetricSeries]:
    """Parse a Prometheus ``/api/v1/query`` vector response into metric series."""
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
    return series


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
