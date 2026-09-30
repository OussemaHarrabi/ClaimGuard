"""Real-PostgreSQL behaviour for the P2 role-aware activity endpoints.

These tests need a live database (skipped automatically when unreachable) because
the activity view is defined entirely by SQL: the role/actor resolution is a join
against the clinic directory, the tenant scope is a real predicate, and the
per-role counts are aggregate queries. The tracing tests use the same app but an
in-process recording tracer, so no collector is needed.

Every row a test creates is removed at teardown: review rows through the
``sandbox`` fixture, intake jobs and test accounts by hand.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from claimguard.clinic.session import SessionSigner
from claimguard.clinic.workspaces import WorkspaceStore
from claimguard.ops import telemetry
from claimguard.review.app import create_app
from claimguard.review.explanations import TemplateExplanationProvider
from claimguard.review.models import ReviewAction
from claimguard.review.store import ReviewStore
from sqlalchemy import Engine, text

from tests.edu import RULES_DIR
from tests.review.conftest import Sandbox, requires_db
from tests.review.test_auth_api import create_test_account, remove_test_account
from tests.review.test_review_store import decide, submit

pytestmark = [pytest.mark.integration, requires_db]

#: A signer key long enough for ``SessionSigner``; the tests never leave process.
_KEY = b"test-key-for-ops-activity-integration-01"

_LEGACY_TENANT = "clinic-legacy-demo"


def _app(store: ReviewStore) -> Any:
    """The review app with the activity/roles routes mounted, over the test store."""
    return create_app(
        store=store,
        rules_dir=RULES_DIR,
        explain_provider=TemplateExplanationProvider(),
        signer=SessionSigner(_KEY),
    )


@asynccontextmanager
async def _client(app: Any) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://review.test"
    ) as client:
        yield client


async def _login(
    client: httpx.AsyncClient, role: str, engine: Engine, accounts: list[str]
) -> tuple[str, str]:
    """Create one active account, sign it in, and remember it for cleanup."""
    user_id, email, password = create_test_account(engine, role)
    accounts.append(user_id)
    response = await client.post(
        "/v1/auth/login",
        json={"tenant_id": _LEGACY_TENANT, "email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == role
    return user_id, email


# ---------------------------------------------------------------------------
# Real entries, filters and resolved role/actor
# ---------------------------------------------------------------------------


async def test_activity_returns_real_entries_with_resolved_role(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    accounts: list[str] = []
    job_ids: list[str] = []
    app = _app(store)
    try:
        reviewer_id, reviewer_email = await _an_account(engine, accounts, "rcm_reviewer")
        tenant = store.for_tenant(_LEGACY_TENANT)
        envelope = sandbox.coverage_lapse()
        run = submit(tenant, envelope, initiated_by=reviewer_id)
        decide(tenant, run.run.run_id, ReviewAction.CONFIRM_ISSUE, actor=reviewer_id)
        job = WorkspaceStore(engine).create_intake_job(
            _LEGACY_TENANT, reviewer_id, "claim.json", json.dumps(envelope)
        )
        job_ids.append(job["job_id"])

        async with _client(app) as client:
            await _login(client, "technical_manager", engine, accounts)
            body = (await client.get("/v1/operations/activity?limit=200")).json()
            assert body["source"]["state"] in {"healthy", "stale"}
            by_area = {
                entry["area"]: entry
                for entry in body["entries"]
                if entry["actor"] == reviewer_email
            }
            assert by_area["claim_submission"]["action"] == "claim_submitted"
            assert by_area["claim_submission"]["role"] == "rcm_reviewer"
            assert by_area["claim_submission"]["reference"] == run.run.run_id
            assert by_area["review_decision"]["action"] == "decision_recorded"
            assert by_area["review_decision"]["outcome"] == "confirm_issue"
            assert by_area["intake"]["action"] == "document_ingested"
            assert by_area["intake"]["outcome"] == "needs_review"

            by_role = (
                await client.get("/v1/operations/activity?role=rcm_reviewer&limit=200")
            ).json()
            assert by_role["role"] == "rcm_reviewer"
            assert by_role["entries"]
            assert all(entry["role"] == "rcm_reviewer" for entry in by_role["entries"])

            by_submission = (
                await client.get("/v1/operations/activity?area=claim_submission&limit=200")
            ).json()
            assert by_submission["area"] == "claim_submission"
            assert by_submission["entries"]
            assert all(entry["area"] == "claim_submission" for entry in by_submission["entries"])

            by_other_role = (
                await client.get("/v1/operations/activity?role=technical_manager&limit=200")
            ).json()
            assert by_other_role["entries"] == []
    finally:
        _cleanup_activity(engine, sandbox, job_ids, accounts, ())


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


async def test_activity_never_leaks_another_tenants_rows(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    accounts: list[str] = []
    job_ids: list[str] = []
    other_clinic = f"clinic-test-{uuid.uuid4().hex}"
    other_user = f"other-user-{uuid.uuid4().hex}"
    other_email = f"{other_user}@example.test"
    app = _app(store)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO claimguard.clinics (tenant_id, name) VALUES (:id, 'Other')"),
                {"id": other_clinic},
            )
            connection.execute(
                text("INSERT INTO claimguard.users (user_id, email) VALUES (:id, :email)"),
                {"id": other_user, "email": other_email},
            )
            connection.execute(
                text(
                    "INSERT INTO claimguard.clinic_memberships (tenant_id, user_id, role) "
                    "VALUES (:tenant, :id, 'rcm_reviewer')"
                ),
                {"tenant": other_clinic, "id": other_user},
            )
        other_envelope = sandbox.claim()
        other_run = submit(store.for_tenant(other_clinic), other_envelope, initiated_by=other_user)

        async with _client(app) as client:
            await _login(client, "technical_manager", engine, accounts)
            response = await client.get("/v1/operations/activity?limit=200")
            assert response.status_code == 200, response.text
            body = response.json()
        references = {entry["reference"] for entry in body["entries"]}
        assert other_run.run.run_id not in references
        assert other_email not in response.text
        assert other_envelope["claim_id"] not in response.text
    finally:
        _cleanup_activity(
            engine, sandbox, job_ids, accounts, ((other_clinic, other_user, other_email),)
        )


# ---------------------------------------------------------------------------
# Roles: every active membership, with real counts
# ---------------------------------------------------------------------------


async def test_roles_lists_every_active_membership_with_real_counts(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    accounts: list[str] = []
    job_ids: list[str] = []
    app = _app(store)
    try:
        reviewer_id, reviewer_email = await _an_account(engine, accounts, "rcm_reviewer")
        envelope = sandbox.coverage_lapse()
        submit(store.for_tenant(_LEGACY_TENANT), envelope, initiated_by=reviewer_id)

        async with _client(app) as client:
            await _login(client, "technical_manager", engine, accounts)
            response = await client.get("/v1/operations/roles")
            assert response.status_code == 200, response.text
            body = response.json()
        roles = {summary["role"]: summary for summary in body["roles"]}
        # The technical manager that just signed in is itself an active membership.
        assert "technical_manager" in roles
        assert roles["technical_manager"]["active_members"] >= 1
        assert "rcm_reviewer" in roles
        summary = roles["rcm_reviewer"]
        assert summary["active_members"] >= 1
        assert reviewer_email in summary["members"]
        assert summary["recent_actions"] >= 1
        assert "claim_submission" in summary["areas"]
        assert summary["last_active_at"] is not None
    finally:
        _cleanup_activity(engine, sandbox, job_ids, accounts, ())


# ---------------------------------------------------------------------------
# No claim content, ever
# ---------------------------------------------------------------------------


async def test_activity_never_returns_claim_content(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    accounts: list[str] = []
    job_ids: list[str] = []
    app = _app(store)
    try:
        reviewer_id, _email = await _an_account(engine, accounts, "rcm_reviewer")
        envelope = sandbox.coverage_lapse()
        submit(store.for_tenant(_LEGACY_TENANT), envelope, initiated_by=reviewer_id)

        async with _client(app) as client:
            await _login(client, "technical_manager", engine, accounts)
            activity = await client.get("/v1/operations/activity?limit=200")
            roles = await client.get("/v1/operations/roles")
        for response in (activity, roles):
            assert response.status_code == 200, response.text
            lowered = response.text.lower()
            assert envelope["claim_id"] not in response.text
            assert "envelope" not in lowered
            assert "patient" not in lowered
            assert "member_id" not in lowered
            assert "diagnosis" not in lowered
    finally:
        _cleanup_activity(engine, sandbox, job_ids, accounts, ())


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


async def test_activity_and_roles_require_read_operations(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    accounts: list[str] = []
    job_ids: list[str] = []
    app = _app(store)
    try:
        async with _client(app) as reviewer:
            await _login(reviewer, "rcm_reviewer", engine, accounts)
            assert (await reviewer.get("/v1/operations/activity")).status_code == 403
            assert (await reviewer.get("/v1/operations/roles")).status_code == 403
        async with _client(app) as technical:
            await _login(technical, "technical_manager", engine, accounts)
            assert (await technical.get("/v1/operations/activity")).status_code == 200
            assert (await technical.get("/v1/operations/roles")).status_code == 200
    finally:
        _cleanup_activity(engine, sandbox, job_ids, accounts, ())


# ---------------------------------------------------------------------------
# Tracing: one span per pipeline stage, and tracing failure never breaks a claim
# ---------------------------------------------------------------------------


class _RecordingManager:
    """A context manager that records the span name it opened."""

    def __init__(self, names: list[str], name: str) -> None:
        self._names = names
        self._name = name

    def __enter__(self) -> object:
        self._names.append(self._name)
        return object()

    def __exit__(self, *exc: object) -> bool:
        return False


class _RecordingTracer:
    """A tracer that records every span name, without an SDK or a collector."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def start_as_current_span(
        self, name: str, *args: object, **kwargs: object
    ) -> _RecordingManager:
        return _RecordingManager(self.names, name)


async def test_submit_creates_a_span_per_pipeline_stage(
    client: httpx.AsyncClient, sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracer = _RecordingTracer()

    def _tracer(name: str) -> object:
        return tracer

    monkeypatch.setattr(telemetry, "get_tracer", _tracer)
    response = await client.post("/v1/claims", json={"claim": sandbox.coverage_lapse()})
    assert response.status_code == 201, response.text
    assert {
        "claim.submit",
        "claim.evaluate",
        "claim.explain",
        "claim.persist",
        "claim.audit",
    } <= set(tracer.names)


async def test_a_tracing_failure_does_not_break_submit_claim(
    client: httpx.AsyncClient, sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(name: str) -> object:
        raise RuntimeError("tracer exploded")

    monkeypatch.setattr(telemetry, "get_tracer", _boom)
    response = await client.post("/v1/claims", json={"claim": sandbox.coverage_lapse()})
    assert response.status_code == 201, response.text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _an_account(engine: Engine, accounts: list[str], role: str) -> tuple[str, str]:
    """Create one active account without signing it in (used as an actor)."""
    user_id, email, _password = create_test_account(engine, role)
    accounts.append(user_id)
    return user_id, email


def _cleanup_activity(
    engine: Engine,
    sandbox: Sandbox,
    job_ids: list[str],
    accounts: list[str],
    other_tenants: tuple[tuple[str, str, str], ...],
) -> None:
    """Remove every row these tests created, in dependency order."""
    for job_id in job_ids:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM claimguard.intake_jobs WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
    sandbox.purge()
    for account in accounts:
        remove_test_account(engine, account)
    for tenant, user, _email in other_tenants:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM claimguard.clinic_memberships WHERE user_id = :id"),
                {"id": user},
            )
            connection.execute(
                text("DELETE FROM claimguard.users WHERE user_id = :id"), {"id": user}
            )
            connection.execute(
                text("DELETE FROM claimguard.clinics WHERE tenant_id = :id"), {"id": tenant}
            )
