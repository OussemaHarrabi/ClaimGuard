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
    MAX_TRACE_SPANS,
    MetricSeries,
    PrometheusSamples,
    PrometheusSource,
    SourceNotFound,
    SourceUnavailable,
    TempoSource,
    TraceSummary,
)

pytestmark = pytest.mark.unit

_METRIC = "claimguard_http_requests_total"

#: The timestamp the shared Prometheus fixture attached to its single sample.
_SAMPLE_AT = datetime.fromtimestamp(1727000000, tz=UTC)


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
    samples = _prometheus(transport).query_samples(300)
    assert samples.series == [
        MetricSeries(
            name=_METRIC,
            labels={"route_template": "/v1/health", "status_class": "2xx"},
            value=7.0,
        )
    ]
    assert samples.last_sample_at == _SAMPLE_AT


def test_prometheus_surfaces_the_newest_sample_timestamp() -> None:
    payload = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {"__name__": _METRIC, "route_template": "/a"},
                    "value": [1727000000.0, "1"],
                },
                {
                    "metric": {"__name__": _METRIC, "route_template": "/b"},
                    "value": [1727000300.0, "2"],
                },
                {
                    "metric": {"__name__": _METRIC, "route_template": "/c"},
                    "value": [1726999000.0, "3"],
                },
            ],
        },
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    samples = _prometheus(transport).query_samples(300)
    assert samples.last_sample_at == datetime.fromtimestamp(1727000300, tz=UTC)
    assert len(samples.series) == 3


@pytest.mark.parametrize("bad_timestamp", ["not-a-number", None, True, {}])
def test_prometheus_ignores_an_unusable_sample_timestamp(bad_timestamp: object) -> None:
    payload: dict[str, object] = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {"__name__": _METRIC, "route_template": "/v1/health"},
                    "value": [bad_timestamp, "5"],
                },
            ],
        },
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    samples = _prometheus(transport).query_samples(300)
    assert samples.last_sample_at is None
    assert samples.series == [
        MetricSeries(
            name=_METRIC,
            labels={"route_template": "/v1/health"},
            value=5.0,
        )
    ]


def test_prometheus_with_no_samples_surfaces_an_empty_result() -> None:
    payload: dict[str, object] = {
        "status": "success",
        "data": {"resultType": "vector", "result": []},
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    assert _prometheus(transport).query_samples(300) == PrometheusSamples(
        series=[], last_sample_at=None
    )


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


# ---------------------------------------------------------------------------
# Tempo: fetching one trace's spans
# ---------------------------------------------------------------------------


def _otlp_trace_payload() -> dict[str, object]:
    """A two-span OTLP JSON trace, one nested and one marked error."""
    return {
        "batches": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "claimguard"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "spanId": "aaaa",
                                "name": "POST /v1/claims",
                                "startTimeUnixNano": "1727000000000000000",
                                "endTimeUnixNano": "1727000000100000000",
                            },
                            {
                                "spanId": "bbbb",
                                "parentSpanId": "aaaa",
                                "name": "claim.evaluate",
                                "startTimeUnixNano": "1727000000020000000",
                                "endTimeUnixNano": "1727000000070000000",
                                "status": {"code": 2},
                            },
                        ]
                    }
                ],
            }
        ]
    }


def test_tempo_get_trace_parses_otlp_spans() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=_otlp_trace_payload()))
    detail = _tempo(transport).get_trace("a" * 32)
    assert detail.trace_id == "a" * 32
    assert [span.span_id for span in detail.spans] == ["aaaa", "bbbb"]
    root, child = detail.spans
    assert root.parent_span_id is None
    assert root.service == "claimguard"
    assert root.duration_ms == 100.0
    assert root.status == "ok"
    assert child.parent_span_id == "aaaa"
    assert child.duration_ms == 50.0
    assert child.status == "error"


def test_tempo_get_trace_accepts_json_explicitly() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"batches": []})

    _tempo(httpx.MockTransport(handler)).get_trace("b" * 32)
    assert seen[0].headers.get("accept") == "application/json"


def test_tempo_get_trace_404_is_source_not_found() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404, json={"error": "x"}))
    with pytest.raises(SourceNotFound):
        _tempo(transport).get_trace("c" * 32)


def test_tempo_get_trace_rejects_a_malformed_id_without_a_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"batches": []})

    with pytest.raises(SourceNotFound):
        _tempo(httpx.MockTransport(handler)).get_trace("../not-a-trace")
    assert seen == []


def test_tempo_get_trace_with_no_spans_returns_an_empty_trace() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"batches": []}))
    assert _tempo(transport).get_trace("d" * 32).spans == []


def test_tempo_get_trace_caps_the_span_count() -> None:
    spans = [
        {
            "spanId": f"{index:04d}",
            "name": f"span-{index}",
            "startTimeUnixNano": str(1727000000000000000 + index),
            "endTimeUnixNano": str(1727000000000000000 + index + 1),
        }
        for index in range(MAX_TRACE_SPANS + 50)
    ]
    payload = {"batches": [{"scopeSpans": [{"spans": spans}]}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    detail = _tempo(transport).get_trace("e" * 32)
    assert len(detail.spans) == MAX_TRACE_SPANS
