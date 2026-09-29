"""Unit tests for the P2 operational source clients.

No network and no database: every HTTP interaction runs through an in-process
``httpx.MockTransport``. The tests pin the three things the clients promise —
a healthy source parses into the documented models, a broken source raises
:class:`SourceUnavailable` (never returns an empty success), and no credential
or response body ever leaves the client.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
import pytest
from claimguard.ops.sources import (
    MetricSeries,
    PrometheusSource,
    SourceUnavailable,
    TempoSource,
    TraceSummary,
)

pytestmark = pytest.mark.unit

_METRIC = "claimguard_http_requests_total"


def _prometheus(transport: httpx.MockTransport) -> PrometheusSource:
    return PrometheusSource(
        base_url="http://prometheus.test",
        timeout_seconds=1.0,
        metric_names=(_METRIC,),
        transport=transport,
    )


def _tempo(transport: httpx.MockTransport) -> TempoSource:
    return TempoSource(
        base_url="http://tempo.test",
        timeout_seconds=1.0,
        transport=transport,
    )


def _prometheus_vector(name: str, value: str) -> dict[str, object]:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {
                        "__name__": name,
                        "route_template": "/v1/health",
                        "status_class": "2xx",
                    },
                    "value": [1727000000.0, value],
                }
            ],
        },
    }


# ---------------------------------------------------------------------------
# Healthy parsing
# ---------------------------------------------------------------------------


def test_prometheus_returns_parsed_series() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=_prometheus_vector(_METRIC, "7"))
    )
    series = _prometheus(transport).query_samples(300)
    assert series == [
        MetricSeries(
            name=_METRIC,
            labels={"route_template": "/v1/health", "status_class": "2xx"},
            value=7.0,
        )
    ]


def test_prometheus_builds_the_query_from_allow_listed_parts() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["query"])
        return httpx.Response(200, json=_prometheus_vector(_METRIC, "1"))

    _prometheus(httpx.MockTransport(handler)).query_samples(900)
    assert seen == [f"last_over_time({_METRIC}[900s])"]


def test_tempo_returns_parsed_traces() -> None:
    started = datetime.fromtimestamp(1727000000, tz=UTC)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "traces": [
                    {
                        "traceID": "abc123",
                        "rootServiceName": "claimguard",
                        "rootTraceName": "GET /v1/health",
                        "startTimeUnixNano": "1727000000000000000",
                        "durationMs": 12.5,
                    }
                ]
            },
        )
    )
    assert _tempo(transport).search_traces(20) == [
        TraceSummary(
            trace_id="abc123",
            root_name="GET /v1/health",
            service="claimguard",
            start_time=started,
            duration_ms=12.5,
        )
    ]


# ---------------------------------------------------------------------------
# Failure discipline
# ---------------------------------------------------------------------------


def test_prometheus_timeout_raises_source_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    with pytest.raises(SourceUnavailable):
        _prometheus(httpx.MockTransport(handler)).query_samples(300)


def test_prometheus_http_500_raises_source_unavailable() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500, json={"error": "boom"}))
    with pytest.raises(SourceUnavailable):
        _prometheus(transport).query_samples(300)


def test_prometheus_unparsable_body_raises_source_unavailable() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"status": "success"}))
    with pytest.raises(SourceUnavailable):
        _prometheus(transport).query_samples(300)


def test_tempo_timeout_raises_source_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    with pytest.raises(SourceUnavailable):
        _tempo(httpx.MockTransport(handler)).search_traces(20)


def test_tempo_http_500_raises_source_unavailable() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500, json={"error": "boom"}))
    with pytest.raises(SourceUnavailable):
        _tempo(transport).search_traces(20)


def test_a_metric_outside_the_allow_list_is_refused() -> None:
    with pytest.raises(ValueError):
        PrometheusSource("http://prometheus.test", metric_names=("up",))


# ---------------------------------------------------------------------------
# No credentials, no body logging
# ---------------------------------------------------------------------------


def test_no_credentials_or_body_are_sent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_prometheus_vector(_METRIC, "1"))

    _prometheus(httpx.MockTransport(handler)).query_samples(300)
    assert seen, "the source should have made a request"
    names = {name.lower() for name in seen[0].headers}
    assert "authorization" not in names
    assert "cookie" not in names
    assert seen[0].content == b""


def test_the_response_body_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    marker = "SECRET-RESPONSE-MARKER"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": marker})

    source = _prometheus(httpx.MockTransport(handler))
    with caplog.at_level(logging.DEBUG), pytest.raises(SourceUnavailable):
        source.query_samples(300)
    assert marker not in caplog.text
