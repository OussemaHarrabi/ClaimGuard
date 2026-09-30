"""Unit tests for the P2 role-aware activity operations endpoints.

No database and no network: the router is mounted on a bare FastAPI app with an
injected engine that is deliberately broken, so the fail-open contract (a normal
``200`` with the source marked ``unavailable``) runs without a live PostgreSQL. A
tiny middleware resolves a real :class:`Principal` onto ``request.state`` so the
production ``READ_OPERATIONS`` guard runs unchanged. The tests also pin the
bounded query parameters, the frozen response shape, the absence of claim
content, and the fail-open span helper.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Generator
from typing import Any

import httpx
import pytest
from claimguard.clinic.access import Principal, Role
from claimguard.ops import telemetry
from claimguard.ops.activity import (
    DEFAULT_ACTIVITY_LIMIT,
    MAX_ACTIVITY_LIMIT,
    router,
)
from fastapi import FastAPI, Request, Response

pytestmark = pytest.mark.unit

#: The principal the behavioural tests run as: the role operations is for.
_OPS_PRINCIPAL = Principal(user_id="ops-1", tenant_id="clinic-1", role=Role.TECHNICAL_MANAGER)

#: Every activity path, used by the uniform authorization checks.
_ACTIVITY_PATHS = ("/v1/operations/activity", "/v1/operations/roles")


class _UnavailableEngine:
    """An engine whose every transaction fails, standing in for a dead database."""

    def begin(self) -> Any:
        raise RuntimeError("database unavailable")

    def connect(self) -> Any:
        raise RuntimeError("database unavailable")


def _app(principal: Principal | None = _OPS_PRINCIPAL) -> FastAPI:
    """Mount the activity router on a bare app with an unavailable engine."""
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
    app.state.activity_engine = _UnavailableEngine()
    return app


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://ops.test") as client:
        return await client.get(path)


# ---------------------------------------------------------------------------
# Fail-open: 200 with an honest degradation, never a 500
# ---------------------------------------------------------------------------


async def test_activity_degrades_to_unavailable_without_500() -> None:
    response = await _get(_app(), "/v1/operations/activity")
    assert response.status_code == 200
    body = response.json()
    assert body["source"]["state"] == "unavailable"
    assert body["source"]["last_data_at"] is None
    assert body["source"]["detail"]
    assert body["entries"] == []
    assert body["limit"] == DEFAULT_ACTIVITY_LIMIT


async def test_roles_degrades_to_no_roles_without_500() -> None:
    response = await _get(_app(), "/v1/operations/roles")
    assert response.status_code == 200
    body = response.json()
    assert body["roles"] == []
    assert isinstance(body["checked_at"], str)


# ---------------------------------------------------------------------------
# Bounded parameters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("limit", ["0", "201", "-1", "1000"])
async def test_the_activity_limit_is_bounded(limit: str) -> None:
    response = await _get(_app(), f"/v1/operations/activity?limit={limit}")
    assert response.status_code == 422


async def test_the_default_activity_limit_is_fifty() -> None:
    body = (await _get(_app(), "/v1/operations/activity")).json()
    assert body["limit"] == DEFAULT_ACTIVITY_LIMIT == 50
    assert MAX_ACTIVITY_LIMIT == 200


@pytest.mark.parametrize("query", ["role=bogus_role", "area=bogus_area"])
async def test_an_unknown_filter_is_rejected(query: str) -> None:
    response = await _get(_app(), f"/v1/operations/activity?{query}")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Authorization: READ_OPERATIONS is required and fails closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _ACTIVITY_PATHS)
async def test_a_non_operations_role_is_denied(path: str) -> None:
    reviewer = Principal(user_id="r-1", tenant_id="clinic-1", role=Role.RCM_REVIEWER)
    assert (await _get(_app(reviewer), path)).status_code == 403


@pytest.mark.parametrize("path", _ACTIVITY_PATHS)
async def test_an_absent_principal_fails_closed(path: str) -> None:
    assert (await _get(_app(principal=None), path)).status_code == 403


@pytest.mark.parametrize("path", _ACTIVITY_PATHS)
async def test_the_technical_manager_is_allowed(path: str) -> None:
    assert (await _get(_app(), path)).status_code == 200


# ---------------------------------------------------------------------------
# Shape: no claim content, only the frozen key sets
# ---------------------------------------------------------------------------


async def test_the_activity_response_carries_no_claim_content() -> None:
    response = await _get(_app(), "/v1/operations/activity")
    assert set(response.json()) == {"source", "role", "area", "limit", "entries"}
    lowered = response.text.lower()
    for forbidden in ("envelope", "claim_id", "patient", "member_id", "diagnosis"):
        assert forbidden not in lowered


async def test_the_roles_response_carries_no_claim_content() -> None:
    response = await _get(_app(), "/v1/operations/roles")
    assert set(response.json()) == {"checked_at", "roles"}
    lowered = response.text.lower()
    for forbidden in ("envelope", "claim_id", "patient", "member_id", "diagnosis"):
        assert forbidden not in lowered


# ---------------------------------------------------------------------------
# The fail-open span helper (tracing can never break the claim flow)
# ---------------------------------------------------------------------------


class _RecordingManager:
    """A context manager that stands in for an active span."""

    def __enter__(self) -> object:
        return object()

    def __exit__(self, *exc: object) -> bool:
        return False


class _RecordingTracer:
    """A tracer that records every span name it is asked to start."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def start_as_current_span(
        self, name: str, *args: object, **kwargs: object
    ) -> _RecordingManager:
        self.names.append(name)
        return _RecordingManager()


def test_span_opens_and_closes_a_named_span(monkeypatch: pytest.MonkeyPatch) -> None:
    tracer = _RecordingTracer()

    def _tracer(name: str) -> object:
        return tracer

    monkeypatch.setattr(telemetry, "get_tracer", _tracer)
    with telemetry.span("claim.evaluate", {"version": "1.0"}):
        pass
    assert tracer.names == ["claim.evaluate"]


def test_span_swallows_a_failing_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(name: str) -> object:
        raise RuntimeError("tracer exploded")

    monkeypatch.setattr(telemetry, "get_tracer", _boom)
    ran = False
    with telemetry.span("claim.persist"):
        ran = True
    assert ran is True


def test_span_swallows_a_failing_start(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenTracer:
        def start_as_current_span(self, name: str, *args: object, **kwargs: object) -> object:
            raise RuntimeError("cannot start a span")

    def _tracer(name: str) -> object:
        return _BrokenTracer()

    monkeypatch.setattr(telemetry, "get_tracer", _tracer)
    ran = False
    with telemetry.span("claim.audit"):
        ran = True
    assert ran is True


def test_record_domain_metric_is_a_silent_noop_when_disabled() -> None:
    telemetry.shutdown_telemetry()
    telemetry.record_domain_metric("claimguard_claims_submitted_total", "submitted")
    telemetry.record_domain_metric("claimguard_decisions_total", "not_a_real_action")


@pytest.fixture(autouse=True)
def _restore_telemetry() -> Generator[None, None, None]:  # pyright: ignore[reportUnusedFunction]
    """Leave the global telemetry state uninitialized after each test."""
    yield
    telemetry.shutdown_telemetry()
