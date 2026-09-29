"""Unit tests for the P2 Technical Reviewer operations API.

No database and no network: the router is mounted on a bare FastAPI app whose
Prometheus/Tempo clients and audit seam are injected stubs. A tiny middleware
resolves a real :class:`Principal` onto ``request.state`` so the production
``READ_OPERATIONS`` guard runs unchanged; the security tests below pin that
guard (non-operations roles and absent principals get ``403``). The tests also
pin the degradation contract — a dead source is a normal ``200`` with the source
marked ``unavailable``, never a ``500`` — along with the bounded query
parameters and the audit check's refusal to claim unverified success.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from claimguard.clinic.access import Principal, Role
from claimguard.ops.operations import (
    AuditStatus,
    OperationsCache,
    router,
)
from claimguard.ops.sources import MetricSeries, PrometheusSamples, SourceUnavailable, TraceSummary
from fastapi import FastAPI, Request, Response

pytestmark = pytest.mark.unit

#: The principal the behavioural tests run as: the role operations is for.
_OPS_PRINCIPAL = Principal(user_id="ops-1", tenant_id="clinic-1", role=Role.TECHNICAL_MANAGER)

#: Every operations path, used by the uniform authorization checks.
_OPERATIONS_PATHS = (
    "/v1/operations/overview",
    "/v1/operations/metrics",
    "/v1/operations/traces",
    "/v1/operations/audit",
)


class _UnavailablePrometheus:
    """A Prometheus that is entirely down."""

    def query_samples(self, window_seconds: int) -> list[MetricSeries]:
        raise SourceUnavailable("prometheus timed out")


class _UnavailableTempo:
    """A Tempo that is entirely down."""

    def search_traces(self, limit: int) -> list[TraceSummary]:
        raise SourceUnavailable("tempo timed out")


class _HealthyPrometheus:
    """A Prometheus answering with one timestamped sample."""

    def query_samples(self, window_seconds: int) -> PrometheusSamples:
        return PrometheusSamples(
            series=[
                MetricSeries(
                    name="claimguard_http_requests_total",
                    labels={"status_class": "2xx"},
                    value=3.0,
                )
            ],
            last_sample_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


class _EmptyPrometheus:
    """A Prometheus that answers but has no samples in the window."""

    def query_samples(self, window_seconds: int) -> PrometheusSamples:
        return PrometheusSamples(series=[], last_sample_at=None)


class _EmptyTempo:
    """A Tempo that answers but has no traces in the window."""

    def search_traces(self, limit: int) -> list[TraceSummary]:
        return []


class _HealthyTempo:
    """A Tempo answering with one trace."""

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


class _ReadyStore:
    """A store whose schema check passes without a database."""

    def schema_revision(self) -> str:
        return "0004"


class _ReadyRules:
    """A rule catalogue that loads without a database."""

    def context(self) -> object:
        return object()


def _app(
    *,
    prometheus: Any,
    tempo: Any,
    audit_check: Any = None,
    store: Any = None,
    rules: Any = None,
    principal: Principal | None = _OPS_PRINCIPAL,
) -> FastAPI:
    """Mount the operations router on a bare app with injected collaborators.

    A real principal is installed on ``request.state`` through middleware unless
    ``principal`` is ``None``, which leaves the state unset to exercise the
    fail-closed path.
    """
    app = FastAPI()
    if principal is not None:
        resolved = principal

        async def _install_principal(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            request.state.principal = resolved
            return await call_next(request)

        app.middleware("http")(_install_principal)

    app.include_router(router)
    app.state.prometheus_source = prometheus
    app.state.tempo_source = tempo
    # No caching inside a single test: TTL zero means every request re-probes.
    app.state.operations_cache = OperationsCache(ttl_seconds=0.0)
    if audit_check is not None:
        app.state.audit_check = audit_check
    if store is not None:
        app.state.store = store
    if rules is not None:
        app.state.rules = rules
    return app


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://ops.test") as client:
        return await client.get(path)


# ---------------------------------------------------------------------------
# Degradation: 200, never 500
# ---------------------------------------------------------------------------


async def test_every_endpoint_degrades_but_never_500s() -> None:
    def failing_audit() -> AuditStatus:
        raise RuntimeError("audit database unavailable")

    app = _app(
        prometheus=_UnavailablePrometheus(),
        tempo=_UnavailableTempo(),
        audit_check=failing_audit,
    )

    overview = await _get(app, "/v1/operations/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["status"] == "degraded"
    assert {source["name"] for source in body["sources"]} == {"prometheus", "tempo"}
    assert all(source["state"] == "unavailable" for source in body["sources"])
    assert all(source["detail"] for source in body["sources"])

    metrics = await _get(app, "/v1/operations/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["source"]["state"] == "unavailable"
    assert metrics.json()["series"] == []

    traces = await _get(app, "/v1/operations/traces")
    assert traces.status_code == 200
    assert traces.json()["source"]["state"] == "unavailable"
    assert traces.json()["traces"] == []

    audit = await _get(app, "/v1/operations/audit")
    assert audit.status_code == 200
    assert audit.json()["intact"] is False


async def test_overview_always_lists_the_component_checks() -> None:
    app = _app(prometheus=_UnavailablePrometheus(), tempo=_UnavailableTempo())
    body = (await _get(app, "/v1/operations/overview")).json()
    assert {component["name"] for component in body["components"]} == {
        "api",
        "database",
        "rules",
    }
    assert body["status"] == "degraded"


async def test_overview_is_ok_when_components_and_sources_are_healthy() -> None:
    app = _app(
        prometheus=_HealthyPrometheus(),
        tempo=_HealthyTempo(),
        store=_ReadyStore(),
        rules=_ReadyRules(),
    )
    body = (await _get(app, "/v1/operations/overview")).json()
    assert body["status"] == "ok"
    assert body["versions"]["schema_revision"] == "0004"
    assert all(component["state"] == "healthy" for component in body["components"])
    assert all(source["state"] == "healthy" for source in body["sources"])


async def test_a_healthy_source_reports_when_data_was_seen() -> None:
    app = _app(
        prometheus=_HealthyPrometheus(),
        tempo=_HealthyTempo(),
        store=_ReadyStore(),
        rules=_ReadyRules(),
    )
    body = (await _get(app, "/v1/operations/overview")).json()
    sources = {source["name"]: source for source in body["sources"]}
    assert sources["prometheus"]["state"] == "healthy"
    assert sources["prometheus"]["last_data_at"] is not None
    assert sources["prometheus"]["detail"] is None
    assert sources["tempo"]["last_data_at"] is not None


async def test_a_reachable_but_empty_source_stays_healthy_without_a_time() -> None:
    app = _app(
        prometheus=_EmptyPrometheus(),
        tempo=_EmptyTempo(),
        store=_ReadyStore(),
        rules=_ReadyRules(),
    )
    body = (await _get(app, "/v1/operations/overview")).json()
    sources = {source["name"]: source for source in body["sources"]}
    assert sources["prometheus"]["state"] == "healthy"
    assert sources["prometheus"]["last_data_at"] is None
    assert "no samples" in sources["prometheus"]["detail"]
    assert sources["tempo"]["state"] == "healthy"
    assert sources["tempo"]["last_data_at"] is None
    assert "no traces" in sources["tempo"]["detail"]


async def test_metrics_reports_the_observed_sample_time() -> None:
    app = _app(prometheus=_HealthyPrometheus(), tempo=_HealthyTempo())
    body = (await _get(app, "/v1/operations/metrics")).json()
    assert body["source"]["state"] == "healthy"
    assert body["source"]["last_data_at"] is not None
    assert body["source"]["detail"] is None


async def test_metrics_states_an_empty_window_without_inventing_a_time() -> None:
    app = _app(prometheus=_EmptyPrometheus(), tempo=_HealthyTempo())
    body = (await _get(app, "/v1/operations/metrics")).json()
    assert body["source"]["state"] == "healthy"
    assert body["source"]["last_data_at"] is None
    assert "no samples" in body["source"]["detail"]
    assert body["series"] == []


async def test_traces_states_an_empty_window_without_inventing_a_time() -> None:
    app = _app(prometheus=_HealthyPrometheus(), tempo=_EmptyTempo())
    body = (await _get(app, "/v1/operations/traces")).json()
    assert body["source"]["state"] == "healthy"
    assert body["source"]["last_data_at"] is None
    assert "no traces" in body["source"]["detail"]
    assert body["traces"] == []


# ---------------------------------------------------------------------------
# Bounded parameters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("window", ["99m", "0m", "2h", "forever"])
async def test_the_metric_window_is_bounded(window: str) -> None:
    app = _app(prometheus=_HealthyPrometheus(), tempo=_HealthyTempo())
    response = await _get(app, f"/v1/operations/metrics?window={window}")
    assert response.status_code == 422


async def test_the_default_metric_window_is_fifteen_minutes() -> None:
    app = _app(prometheus=_HealthyPrometheus(), tempo=_HealthyTempo())
    body = (await _get(app, "/v1/operations/metrics")).json()
    assert body["window"] == "15m"


@pytest.mark.parametrize("limit", ["0", "101", "-1"])
async def test_the_trace_limit_is_bounded(limit: str) -> None:
    app = _app(prometheus=_HealthyPrometheus(), tempo=_HealthyTempo())
    response = await _get(app, f"/v1/operations/traces?limit={limit}")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Audit safety
# ---------------------------------------------------------------------------


async def test_audit_reports_success_when_the_check_passes() -> None:
    app = _app(
        prometheus=_HealthyPrometheus(),
        tempo=_HealthyTempo(),
        audit_check=lambda: AuditStatus(intact=True, event_count=5),
    )
    body = (await _get(app, "/v1/operations/audit")).json()
    assert body["intact"] is True
    assert body["event_count"] == 5


async def test_audit_reports_a_broken_chain_as_not_intact() -> None:
    app = _app(
        prometheus=_HealthyPrometheus(),
        tempo=_HealthyTempo(),
        audit_check=lambda: AuditStatus(intact=False, event_count=5),
    )
    body = (await _get(app, "/v1/operations/audit")).json()
    assert body["intact"] is False


async def test_audit_never_claims_intact_when_the_check_fails() -> None:
    def failing_audit() -> AuditStatus:
        raise RuntimeError("boom")

    app = _app(
        prometheus=_HealthyPrometheus(),
        tempo=_HealthyTempo(),
        audit_check=failing_audit,
    )
    body = (await _get(app, "/v1/operations/audit")).json()
    assert body["intact"] is False
    assert body["detail"] is None


# ---------------------------------------------------------------------------
# Authorization: READ_OPERATIONS is required and fails closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _OPERATIONS_PATHS)
async def test_a_non_operations_role_is_denied(path: str) -> None:
    reviewer = Principal(user_id="r-1", tenant_id="clinic-1", role=Role.RCM_REVIEWER)
    app = _app(
        prometheus=_HealthyPrometheus(),
        tempo=_HealthyTempo(),
        principal=reviewer,
    )
    assert (await _get(app, path)).status_code == 403


@pytest.mark.parametrize("path", _OPERATIONS_PATHS)
async def test_an_absent_principal_fails_closed(path: str) -> None:
    app = _app(
        prometheus=_HealthyPrometheus(),
        tempo=_HealthyTempo(),
        principal=None,
    )
    assert (await _get(app, path)).status_code == 403


@pytest.mark.parametrize("path", _OPERATIONS_PATHS)
async def test_the_technical_manager_is_allowed(path: str) -> None:
    app = _app(
        prometheus=_HealthyPrometheus(),
        tempo=_HealthyTempo(),
        audit_check=lambda: AuditStatus(intact=True, event_count=0),
    )
    assert (await _get(app, path)).status_code == 200
