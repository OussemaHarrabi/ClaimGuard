"""Unit tests for the P2 operations detail endpoints.

Covers the two additions that let the console see *inside* what it already lists:
``GET /v1/operations/traces/{trace_id}`` (one trace's span tree) and
``GET /v1/operations/audit/chain`` (the hash chain, safely). No database and no
network: the operations router is mounted on a bare FastAPI app whose Tempo
client, audit verdict and chain reader are injected stubs. The tests pin the
exact response contracts, the server-computed depth/offsets, the newest-first
chain numbering, the fail-open paths (a dead source never 500s) and the one
deliberate difference — an unknown trace id is a ``404`` — plus the guarantee
that no forbidden audit column can reach the response.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
import pytest
from claimguard.clinic.access import Principal, Role
from claimguard.ops.operations import (
    AuditChainPage,
    AuditChainRow,
    AuditStatus,
    OperationsCache,
    router,
)
from claimguard.ops.sources import (
    SourceNotFound,
    SourceUnavailable,
    TraceDetail,
    TraceSpan,
)
from fastapi import FastAPI, Request, Response

pytestmark = pytest.mark.unit

_OPS_PRINCIPAL = Principal(user_id="ops-1", tenant_id="clinic-1", role=Role.TECHNICAL_MANAGER)

#: Both new paths, used by the uniform authorization checks.
_DETAIL_PATHS = (
    "/v1/operations/traces/aabbccddeeff00112233445566778899",
    "/v1/operations/audit/chain",
)

#: The ledger columns the chain endpoint must never expose.
_FORBIDDEN_LINK_KEYS = {
    "decision",
    "reason_code",
    "finding_ids",
    "rule_version",
    "model_version",
}

_TRACE_ID = "aabbccddeeff00112233445566778899"
_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _span(
    span_id: str,
    parent_span_id: str | None,
    name: str,
    offset_ms: int,
    duration_ms: int,
    *,
    status: Literal["ok", "error"] = "ok",
) -> TraceSpan:
    return TraceSpan(
        span_id=span_id,
        parent_span_id=parent_span_id,
        name=name,
        service="claimguard",
        start_time=_T0 + timedelta(milliseconds=offset_ms),
        duration_ms=float(duration_ms),
        status=status,
    )


class _DetailTempo:
    """A Tempo that answers with a fixed trace detail."""

    def __init__(self, detail: TraceDetail) -> None:
        self._detail = detail

    def get_trace(self, trace_id: str) -> TraceDetail:
        return self._detail


class _NotFoundTempo:
    """A Tempo that holds no trace for the requested id."""

    def get_trace(self, trace_id: str) -> TraceDetail:
        raise SourceNotFound("tempo has no object for this id")


class _UnavailableTempo:
    """A Tempo that cannot answer at all."""

    def get_trace(self, trace_id: str) -> TraceDetail:
        raise SourceUnavailable("tempo timed out")


class _BoomTempo:
    """A Tempo that fails unexpectedly (not a SourceUnavailable)."""

    def get_trace(self, trace_id: str) -> TraceDetail:
        raise RuntimeError("boom")


def _chain_row(
    event_id: str,
    offset_s: int,
    prev_hash: str,
    chain_hash: str,
    *,
    claim_ref: str | None = None,
    kind: str = "validated",
) -> AuditChainRow:
    return AuditChainRow(
        event_id=event_id,
        at=_T0 + timedelta(seconds=offset_s),
        kind=kind,
        prev_hash=prev_hash,
        chain_hash=chain_hash,
        claim_ref=claim_ref,
        trace_id="trace-" + event_id,
    )


def _reader(page: AuditChainPage) -> Callable[[int], AuditChainPage]:
    """A chain-reader seam that always answers with ``page``."""

    def read(limit: int) -> AuditChainPage:
        return page

    return read


def _app(
    *,
    tempo: Any,
    audit_check: Any = None,
    chain_reader: Any = None,
    principal: Principal | None = _OPS_PRINCIPAL,
) -> FastAPI:
    """Mount the operations router with injected collaborators and a principal."""
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
    app.state.tempo_source = tempo
    app.state.operations_cache = OperationsCache(ttl_seconds=0.0)
    if audit_check is not None:
        app.state.audit_check = audit_check
    if chain_reader is not None:
        app.state.audit_chain_reader = chain_reader
    return app


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://ops.test") as client:
        return await client.get(path)


# ---------------------------------------------------------------------------
# Trace detail: the response contract
# ---------------------------------------------------------------------------


async def test_trace_detail_returns_a_server_computed_span_tree() -> None:
    detail = TraceDetail(
        trace_id=_TRACE_ID,
        spans=[
            _span("child", "root", "claim.evaluate", 20, 50),
            _span("root", None, "POST /v1/claims", 0, 100),
            _span("grand", "child", "db.query", 30, 10, status="error"),
        ],
    )
    app = _app(tempo=_DetailTempo(detail))
    body = (await _get(app, f"/v1/operations/traces/{_TRACE_ID}")).json()

    assert set(body) == {"source", "trace_id", "root_name", "duration_ms", "spans"}
    assert body["source"]["state"] == "healthy"
    assert body["trace_id"] == _TRACE_ID
    assert body["root_name"] == "POST /v1/claims"
    assert body["duration_ms"] == 100.0

    assert set(body["spans"][0]) == {
        "span_id",
        "parent_span_id",
        "name",
        "service",
        "start_offset_ms",
        "duration_ms",
        "depth",
        "status",
    }
    assert [span["span_id"] for span in body["spans"]] == ["root", "child", "grand"]
    assert [span["start_offset_ms"] for span in body["spans"]] == [0.0, 20.0, 30.0]
    assert [span["depth"] for span in body["spans"]] == [0, 1, 2]
    assert [span["status"] for span in body["spans"]] == ["ok", "ok", "error"]
    assert body["spans"][0]["parent_span_id"] is None


async def test_trace_detail_caps_the_span_count() -> None:
    spans = [_span(f"s{index}", None, "work", index, 1) for index in range(250)]
    detail = TraceDetail(trace_id=_TRACE_ID, spans=spans)
    app = _app(tempo=_DetailTempo(detail))
    body = (await _get(app, f"/v1/operations/traces/{_TRACE_ID}")).json()
    assert len(body["spans"]) == 200


# ---------------------------------------------------------------------------
# Trace detail: missing vs unavailable
# ---------------------------------------------------------------------------


async def test_an_unknown_trace_id_is_a_404() -> None:
    app = _app(tempo=_NotFoundTempo())
    response = await _get(app, f"/v1/operations/traces/{_TRACE_ID}")
    assert response.status_code == 404
    assert response.json()["detail"]


async def test_a_trace_with_no_spans_is_a_404() -> None:
    app = _app(tempo=_DetailTempo(TraceDetail(trace_id=_TRACE_ID, spans=[])))
    response = await _get(app, f"/v1/operations/traces/{_TRACE_ID}")
    assert response.status_code == 404


async def test_a_dead_tempo_is_fail_open_with_no_spans() -> None:
    app = _app(tempo=_UnavailableTempo())
    response = await _get(app, f"/v1/operations/traces/{_TRACE_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["source"]["state"] == "unavailable"
    assert body["source"]["detail"]
    assert body["spans"] == []


async def test_an_unexpected_tempo_failure_never_500s() -> None:
    app = _app(tempo=_BoomTempo())
    response = await _get(app, f"/v1/operations/traces/{_TRACE_ID}")
    assert response.status_code == 200
    assert response.json()["source"]["state"] == "unavailable"


# ---------------------------------------------------------------------------
# Audit chain: the response contract
# ---------------------------------------------------------------------------


def _three_row_page() -> AuditChainPage:
    return AuditChainPage(
        rows=[
            _chain_row("e3", 3, "h2", "h3", claim_ref="RUN-3", kind="review_decided"),
            _chain_row("e2", 2, "h1", "h2"),
            _chain_row("e1", 1, "genesis", "h1", claim_ref="RUN-1"),
        ],
        total_events=3,
    )


async def test_audit_chain_returns_newest_first_with_sequences() -> None:
    app = _app(
        tempo=_DetailTempo(TraceDetail(trace_id=_TRACE_ID, spans=[])),
        audit_check=lambda: AuditStatus(intact=True, event_count=3),
        chain_reader=_reader(_three_row_page()),
    )
    body = (await _get(app, "/v1/operations/audit/chain")).json()

    assert set(body) == {"intact", "checked_at", "total_events", "links"}
    assert body["intact"] is True
    assert body["total_events"] == 3
    assert [link["event_id"] for link in body["links"]] == ["e3", "e2", "e1"]
    assert [link["sequence"] for link in body["links"]] == [3, 2, 1]
    assert all(link["linked"] for link in body["links"])
    assert set(body["links"][0]) == {
        "sequence",
        "event_id",
        "at",
        "kind",
        "prev_hash",
        "chain_hash",
        "claim_ref",
        "trace_id",
        "linked",
    }
    assert body["links"][0]["claim_ref"] == "RUN-3"
    assert body["links"][1]["claim_ref"] is None


async def test_audit_chain_marks_a_broken_link() -> None:
    broken = AuditChainPage(
        rows=[
            _chain_row("e2", 2, "WRONG", "h2"),
            _chain_row("e1", 1, "genesis", "h1"),
        ],
        total_events=2,
    )
    app = _app(
        tempo=_DetailTempo(TraceDetail(trace_id=_TRACE_ID, spans=[])),
        audit_check=lambda: AuditStatus(intact=False, event_count=2),
        chain_reader=_reader(broken),
    )
    body = (await _get(app, "/v1/operations/audit/chain")).json()
    assert body["intact"] is False
    assert body["links"][0]["linked"] is False
    assert body["links"][1]["linked"] is True


async def test_audit_chain_verifies_the_oldest_shown_link_against_the_extra_row() -> None:
    page = AuditChainPage(
        rows=[
            _chain_row("e0", 4, "x2", "x3"),
            _chain_row("e1", 3, "x1", "x2"),
            _chain_row("e2", 2, "genesis", "x1"),
        ],
        total_events=5,
    )
    app = _app(
        tempo=_DetailTempo(TraceDetail(trace_id=_TRACE_ID, spans=[])),
        audit_check=lambda: AuditStatus(intact=True, event_count=5),
        chain_reader=_reader(page),
    )
    body = (await _get(app, "/v1/operations/audit/chain?limit=2")).json()
    assert [link["sequence"] for link in body["links"]] == [5, 4]
    assert [link["event_id"] for link in body["links"]] == ["e0", "e1"]
    assert all(link["linked"] for link in body["links"])
    assert "_e2" not in str(body)


async def test_audit_chain_never_exposes_a_forbidden_column() -> None:
    app = _app(
        tempo=_DetailTempo(TraceDetail(trace_id=_TRACE_ID, spans=[])),
        audit_check=lambda: AuditStatus(intact=True, event_count=3),
        chain_reader=_reader(_three_row_page()),
    )
    body = (await _get(app, "/v1/operations/audit/chain")).json()
    for link in body["links"]:
        assert not (_FORBIDDEN_LINK_KEYS & set(link))


async def test_audit_chain_fails_open_on_a_database_fault() -> None:
    def failing_reader(limit: int) -> AuditChainPage:
        raise RuntimeError("database unavailable")

    def failing_audit() -> AuditStatus:
        raise RuntimeError("database unavailable")

    app = _app(
        tempo=_DetailTempo(TraceDetail(trace_id=_TRACE_ID, spans=[])),
        audit_check=failing_audit,
        chain_reader=failing_reader,
    )
    response = await _get(app, "/v1/operations/audit/chain")
    assert response.status_code == 200
    body = response.json()
    assert body["intact"] is False
    assert body["total_events"] == 0
    assert body["links"] == []


@pytest.mark.parametrize("limit", ["0", "201", "-1"])
async def test_the_audit_chain_limit_is_bounded(limit: str) -> None:
    app = _app(
        tempo=_DetailTempo(TraceDetail(trace_id=_TRACE_ID, spans=[])),
        audit_check=lambda: AuditStatus(intact=True, event_count=0),
        chain_reader=_reader(AuditChainPage(rows=[], total_events=0)),
    )
    response = await _get(app, f"/v1/operations/audit/chain?limit={limit}")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Authorization: READ_OPERATIONS is required and fails closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _DETAIL_PATHS)
async def test_a_non_operations_role_is_denied(path: str) -> None:
    reviewer = Principal(user_id="r-1", tenant_id="clinic-1", role=Role.RCM_REVIEWER)
    app = _app(
        tempo=_DetailTempo(TraceDetail(trace_id=_TRACE_ID, spans=[])),
        principal=reviewer,
    )
    assert (await _get(app, path)).status_code == 403


@pytest.mark.parametrize("path", _DETAIL_PATHS)
async def test_an_absent_principal_fails_closed(path: str) -> None:
    app = _app(
        tempo=_DetailTempo(TraceDetail(trace_id=_TRACE_ID, spans=[])),
        principal=None,
    )
    assert (await _get(app, path)).status_code == 403


@pytest.mark.parametrize("path", _DETAIL_PATHS)
async def test_the_technical_manager_is_allowed(path: str) -> None:
    app = _app(
        tempo=_DetailTempo(
            TraceDetail(
                trace_id=_TRACE_ID,
                spans=[_span("root", None, "POST /v1/claims", 0, 5)],
            )
        ),
        audit_check=lambda: AuditStatus(intact=True, event_count=0),
        chain_reader=_reader(AuditChainPage(rows=[], total_events=0)),
    )
    assert (await _get(app, path)).status_code == 200
