"""Unit tests for the P2 real-time operations stream.

No database and no network: the stream is mounted on the review app through
:func:`claimguard.review.app.create_app`, whose store, clinic directory,
Prometheus/Tempo clients and audit seam are replaced with in-process stubs. The
session is a real signed cookie, so the shared resolver runs unchanged and the
tests pin the two rejection close codes (``4401`` unauthenticated, ``4403``
missing ``READ_OPERATIONS``) along with the frozen snapshot/ping contract,
change detection and the fail-open degradation of a raising source.
"""

from __future__ import annotations

import warnings
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from claimguard.clinic.access import Role
from claimguard.clinic.directory import ClinicDirectory
from claimguard.clinic.session import SessionSigner
from claimguard.ops.operations import AuditStatus, OperationsCache
from claimguard.ops.sources import MetricSeries, PrometheusSamples, TraceSummary
from claimguard.review.app import create_app
from claimguard.review.explanations import TemplateExplanationProvider
from claimguard.review.store import ReviewStore
from fastapi import FastAPI
from starlette.websockets import WebSocketDisconnect

# Starlette's TestClient touches ``anyio.abc.BlockingPortal``, which now aliases
# ``anyio.from_thread.BlockingPortal`` with a DeprecationWarning; the suite runs
# with warnings as errors, so the import is isolated (see ``filterwarnings``).
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from fastapi.testclient import TestClient
    from starlette.testclient import WebSocketTestSession

pytestmark = pytest.mark.unit

#: A signer key long enough for ``SessionSigner``; the tests never leave process.
_KEY = b"test-key-for-operations-stream-0123456789"

#: The cookie name the middleware and the stream both read.
_COOKIE = "claimguard_session"

#: Short cadences so a ping or a change does not cost the suite real seconds.
_POLL_SECONDS = 0.01
_HEARTBEAT_SECONDS = 0.03


class _ReadyStore:
    """A store whose schema check passes without a database."""

    def schema_revision(self) -> str:
        return "0010"


class _ReadyRules:
    """A rule catalogue that loads without a database."""

    def context(self) -> object:
        return object()


class _StaticDirectory:
    """A clinic directory whose one membership is fixed by the test."""

    def __init__(self, role: Role | None) -> None:
        self._role = role

    def membership(self, user_id: str, tenant_id: str) -> Role | None:
        return self._role


class _MutablePrometheus:
    """A reachable Prometheus whose single sample the test can change."""

    def __init__(self, value: float = 1.0) -> None:
        self.value = value

    def query_samples(self, window_seconds: int) -> PrometheusSamples:
        return PrometheusSamples(
            series=[
                MetricSeries(
                    name="claimguard_http_requests_total",
                    labels={"status_class": "2xx"},
                    value=self.value,
                )
            ],
            last_sample_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


class _HealthyTempo:
    """A reachable Tempo with one trace."""

    def search_traces(self, limit: int) -> list[TraceSummary]:
        return [
            TraceSummary(
                trace_id="t1",
                root_name="GET /v1/health",
                service="claimguard",
                start_time=datetime(2026, 1, 1, tzinfo=UTC),
                duration_ms=4.0,
            )
        ]


class _ExplodingPrometheus:
    """A Prometheus that answers by raising a non-``SourceUnavailable`` error."""

    def query_samples(self, window_seconds: int) -> PrometheusSamples:
        raise RuntimeError("prometheus exploded mid-query")


class _UnavailableEngine:
    """An engine whose every transaction fails, standing in for a dead database."""

    def begin(self) -> Any:
        raise RuntimeError("database unavailable")

    def connect(self) -> Any:
        raise RuntimeError("database unavailable")


def _app(
    *,
    role: Role,
    prometheus: Any = None,
    tempo: Any = None,
    cache_ttl: float = 0.0,
) -> tuple[FastAPI, str]:
    """Build the review app with injected collaborators and a signed session."""
    signer = SessionSigner(_KEY)
    token = signer.issue("user-1", "clinic-1")
    directory = _StaticDirectory(role)
    app = create_app(
        store=cast(ReviewStore, _ReadyStore()),
        explain_provider=TemplateExplanationProvider(),
        signer=signer,
        directory=cast(ClinicDirectory, directory),
    )
    app.state.store = _ReadyStore()
    app.state.rules = _ReadyRules()
    app.state.prometheus_source = prometheus if prometheus is not None else _MutablePrometheus()
    app.state.tempo_source = tempo if tempo is not None else _HealthyTempo()
    app.state.audit_check = lambda: AuditStatus(intact=True, event_count=2)
    app.state.operations_cache = OperationsCache(ttl_seconds=cache_ttl)
    app.state.ops_stream_interval_seconds = _POLL_SECONDS
    app.state.ops_stream_heartbeat_seconds = _HEARTBEAT_SECONDS
    return app, token


def _next_snapshot(websocket: WebSocketTestSession, attempts: int = 200) -> dict[str, Any]:
    """Read frames until a snapshot arrives, skipping heartbeats."""
    for _ in range(attempts):
        message = websocket.receive_json()
        if message["type"] == "snapshot":
            return cast("dict[str, Any]", message)
    raise AssertionError("no snapshot arrived")


# ---------------------------------------------------------------------------
# Authorization: 4401 unauthenticated, 4403 for a role without READ_OPERATIONS
# ---------------------------------------------------------------------------


def test_no_session_cookie_is_closed_with_4401() -> None:
    app, _ = _app(role=Role.TECHNICAL_MANAGER)
    with (
        TestClient(app) as client,
        client.websocket_connect("/v1/operations/stream") as websocket,
        pytest.raises(WebSocketDisconnect) as excinfo,
    ):
        websocket.receive_json()
    assert excinfo.value.code == 4401


def test_a_role_without_read_operations_is_closed_with_4403() -> None:
    app, token = _app(role=Role.RCM_REVIEWER)
    with (
        TestClient(app, cookies={_COOKIE: token}) as client,
        client.websocket_connect("/v1/operations/stream") as websocket,
        pytest.raises(WebSocketDisconnect) as excinfo,
    ):
        websocket.receive_json()
    assert excinfo.value.code == 4403


# ---------------------------------------------------------------------------
# The frozen frame contract
# ---------------------------------------------------------------------------


def test_the_immediate_snapshot_matches_the_rest_overview() -> None:
    app, token = _app(role=Role.TECHNICAL_MANAGER, cache_ttl=5.0)
    with TestClient(app, cookies={_COOKIE: token}) as client:
        rest = client.get("/v1/operations/overview")
        assert rest.status_code == 200, rest.text
        with client.websocket_connect("/v1/operations/stream?section=overview") as websocket:
            message = websocket.receive_json()
    assert message["type"] == "snapshot"
    assert message["section"] == "overview"
    assert isinstance(message["at"], str)
    # `checked_at` is stamped per build on both surfaces, so it is expected to
    # differ; everything else must match the REST view exactly.
    stream_payload = dict(message["payload"])
    rest_payload = dict(rest.json())
    stream_payload.pop("checked_at", None)
    rest_payload.pop("checked_at", None)
    assert stream_payload == rest_payload


def test_section_and_window_select_the_payload_and_switching_reroutes() -> None:
    app, token = _app(role=Role.TECHNICAL_MANAGER)
    with (
        TestClient(app, cookies={_COOKIE: token}) as client,
        client.websocket_connect("/v1/operations/stream?section=metrics&window=5m") as websocket,
    ):
        first = websocket.receive_json()
        assert first["type"] == "snapshot"
        assert first["section"] == "metrics"
        assert first["payload"]["window"] == "5m"
        websocket.send_json({"section": "traces"})
        switched = _next_snapshot(websocket)
    assert switched["section"] == "traces"
    assert "traces" in switched["payload"]


# ---------------------------------------------------------------------------
# Change detection: no spam when unchanged, a snapshot when changed
# ---------------------------------------------------------------------------


def test_an_unchanged_payload_pings_and_a_changed_payload_snapshots() -> None:
    prometheus = _MutablePrometheus(value=1.0)
    app, token = _app(role=Role.TECHNICAL_MANAGER, prometheus=prometheus)
    with (
        TestClient(app, cookies={_COOKIE: token}) as client,
        client.websocket_connect("/v1/operations/stream?section=metrics") as websocket,
    ):
        first = websocket.receive_json()
        assert first["type"] == "snapshot"
        assert first["payload"]["series"][0]["value"] == 1.0
        for _ in range(3):
            unchanged = websocket.receive_json()
            assert unchanged["type"] == "ping"
        prometheus.value = 2.0
        changed = _next_snapshot(websocket)
    assert changed["payload"]["series"][0]["value"] == 2.0


# ---------------------------------------------------------------------------
# Fail-open: a dead source degrades the snapshot, it never sends an error frame
# ---------------------------------------------------------------------------


def test_a_raising_source_degrades_the_snapshot_instead_of_erroring() -> None:
    app, token = _app(role=Role.TECHNICAL_MANAGER, prometheus=_ExplodingPrometheus())
    with (
        TestClient(app, cookies={_COOKIE: token}) as client,
        client.websocket_connect("/v1/operations/stream?section=metrics") as websocket,
    ):
        message = websocket.receive_json()
    assert message["type"] == "snapshot"
    assert message["payload"]["source"]["state"] == "unavailable"
    assert message["payload"]["series"] == []


# ---------------------------------------------------------------------------
# The extended stream: activity and roles stream live on the same machinery
# ---------------------------------------------------------------------------


def test_activity_and_roles_sections_stream_their_payloads() -> None:
    app, token = _app(role=Role.TECHNICAL_MANAGER)
    app.state.activity_engine = _UnavailableEngine()
    with TestClient(app, cookies={_COOKIE: token}) as client:
        with client.websocket_connect("/v1/operations/stream?section=activity") as websocket:
            activity = websocket.receive_json()
        with client.websocket_connect("/v1/operations/stream?section=roles") as websocket:
            roles = websocket.receive_json()
    assert activity["type"] == "snapshot"
    assert activity["section"] == "activity"
    assert activity["payload"]["source"]["state"] == "unavailable"
    assert activity["payload"]["entries"] == []
    assert roles["type"] == "snapshot"
    assert roles["section"] == "roles"
    assert roles["payload"]["roles"] == []
