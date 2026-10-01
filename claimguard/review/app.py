"""FastAPI surface for the reviewer workflow (MVP behaviours 4, 5 and 7).

WHAT THIS SURFACE IS
--------------------
Eight honest operations, and nothing that decides anything about a claim:

=====================================  ==============================================
``POST /v1/claims``                    validate the envelope, run the 15 checks,
                                       persist the run and its audit event
``GET  /v1/runs/{run_id}``             one run's identity, versions and provenance
``GET  /v1/runs/{run_id}/claim``       the immutable input, for drafting a correction
``GET  /v1/runs/{run_id}/results``     the 15 records, exactly as the CLI emits them,
                                       plus each explanation's provenance
``GET  /v1/runs/{run_id}/decisions``   the run's decision history with review states
``GET  /v1/queue``                     the review queue: filters, original values
                                       and unresolved-check counts
``POST /v1/runs/{run_id}/decisions``   record one of the pack's four actions
``POST /v1/claims/{claim_id}/recheck`` a corrected envelope as a NEW version,
                                       leaving the original run untouched
=====================================  ==============================================

``GET /v1/health`` reports schema readiness and the rule catalogue it loaded.

BOUNDARIES THE SURFACE KEEPS
----------------------------
*   **The engine decides, the API reports.** Statuses come from
    :func:`claimguard.edu.engine.evaluate_claim`; this module never edits one, and
    cannot: :class:`claimguard.edu.envelope.ResultRecord` forbids a
    ``review_status`` other than ``unreviewed`` and a non-deterministic method.
*   **A decision is not an adjudication.** It is a reviewer's note about a check
    (confirm / dismiss with reason / request information / corrected-for-recheck).
    There is no approve, deny, pay or submit-to-payer path in this package.
*   **Nothing about a run is mutable.** A correction is a new version; the old
    run, its 15 records and its decisions stay readable through the run
    endpoints, and the database refuses to update them.
*   **Explanations are language, not judgement.** The reviewer-facing
    ``explanation`` is produced through the bounded explanation layer
    (:mod:`claimguard.review.explanations`): the deterministic template by
    default, a configured model when one is, and the deterministic text whenever
    a model path fails. Which of those happened is recorded per record in the
    ``run_explanations`` sidecar and served beside the records by
    ``GET /v1/runs/{run_id}/results`` — never inside the 15-key record, whose
    key set is frozen.
*   **Errors are explicit.** An unknown run or finding is 404, a decision the
    state machine forbids (or a recheck with nothing corrected, or a decision on a
    superseded version) is 409, a transport defect is 422 carrying the engine's
    own message, and an unready service is 503 with the command or the setting
    that fixes it — a missing migration (``alembic upgrade head``) or an
    unresolvable rule catalogue (``CLAIMGUARD_RULES_DIR`` /
    ``CLAIMGUARD_PACK_ROOT``).

The engine runs in-process rather than through a subprocess: the CLI in
:mod:`claimguard.edu.run` is the frozen entry point for batch scoring, and
:func:`claimguard.edu.engine.evaluate_claim` is the same code path without the file
round-trip. The rules directory resolves from ``CLAIMGUARD_RULES_DIR``, then
``CLAIMGUARD_PACK_ROOT`` (the pack-locating convention of
``scripts/edu_conformance.py``), then the vendored pack under the repository root.

``app`` at the bottom of this module is a ready instance for
``uvicorn claimguard.review.app:app``; :func:`create_app` exists so tests inject
their own store, rules directory and database.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Final, Literal, cast

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from claimguard.clinic.access import Action, Principal, Role, authorize
from claimguard.clinic.assignments import Assignment, AssignmentStore
from claimguard.clinic.directory import ClinicDirectory, Department, TeamMember
from claimguard.clinic.session import AuthenticationError, SessionSigner
from claimguard.clinic.workspaces import WorkspaceStore
from claimguard.edu.emit import validate_record
from claimguard.edu.engine import evaluate_claim
from claimguard.edu.envelope import (
    RULE_VERSION,
    Claim,
    ContractError,
    ResultRecord,
    Severity,
    Status,
    TransportError,
    validate_transport,
)
from claimguard.edu.policy import RuleContext, RuleDirError
from claimguard.review import ui as review_ui
from claimguard.review.explanations import (
    ExplainedRun,
    ExplanationProvider,
    explain_run,
    explanation_provider,
)
from claimguard.review.models import (
    AuditStamp,
    DecisionHistory,
    DecisionRequest,
    DecisionResponse,
    HealthResponse,
    IllegalReviewTransitionError,
    QueueFilters,
    RecheckRequest,
    ReviewQueue,
    RunClaimResponse,
    RunResponse,
    RunResultsResponse,
    SubmitClaimRequest,
    requires_attention,
    summarize_statuses,
)
from claimguard.review.store import (
    SCHEMA_REVISION,
    FindingNotFoundError,
    NoCorrectionError,
    RecordedRun,
    ReviewStore,
    ReviewStoreError,
    RunNotFoundError,
    RunSupersededError,
    SchemaNotMigratedError,
    build_engine,
)

#: Environment variables consulted for the rule catalogue (pack convention).
RULES_DIR_ENV: Final = "CLAIMGUARD_RULES_DIR"
PACK_ROOT_ENV: Final = "CLAIMGUARD_PACK_ROOT"
_PACK_DIR_NAMES: Final = ("ClaimGuardAI_Student_Starter_Pack",)
_REPO_ROOT: Final = Path(__file__).resolve().parents[2]

#: Status for a claim that cannot be checked because the catalogue cannot be
#: loaded. 503 Service Unavailable is what a temporarily unavailable dependency
#: is: the submission is not at fault, the service is not ready, and the same
#: request can succeed once the deployment is configured. It is the same answer
#: an unmigrated database gets, so "the service is not ready yet" has exactly one
#: shape on this surface — a structured JSON body naming the fix, never a bare
#: 500.
RULES_UNAVAILABLE_STATUS: Final = status.HTTP_503_SERVICE_UNAVAILABLE


def resolve_rules_dir() -> Path:
    """Locate the pack's ``rules/`` directory, or raise :class:`RuleDirError`.

    Order: ``CLAIMGUARD_RULES_DIR`` (explicit), ``CLAIMGUARD_PACK_ROOT`` (the
    convention ``scripts/edu_conformance.py`` already uses), then a search up the
    tree for the vendored pack directory. The catalogue is read read-only.
    """
    explicit = os.environ.get(RULES_DIR_ENV)
    if explicit:
        return _require_rules_dir(Path(explicit))
    pack_root = os.environ.get(PACK_ROOT_ENV)
    if pack_root:
        return _require_rules_dir(Path(pack_root) / "rules")
    candidates: list[Path] = []
    # The repository root first (the pack usually sits beside `claimguard/`), then
    # the ancestors, so a checkout nested anywhere still finds its own pack.
    for parent in (_REPO_ROOT, *_REPO_ROOT.parents):
        for name in _PACK_DIR_NAMES:
            candidates.append(parent / name / name / "rules")
            candidates.append(parent / name / "rules")
        candidates.append(parent / "rules")
    for candidate in candidates:
        if (candidate / "rules.json").is_file():
            return candidate.resolve()
    raise RuleDirError(
        f"rule catalogue not found; set {RULES_DIR_ENV} or {PACK_ROOT_ENV}. Searched:\n  "
        + "\n  ".join(str(candidate) for candidate in candidates[:12])
    )


def _require_rules_dir(candidate: Path) -> Path:
    if not (candidate / "rules.json").is_file():
        raise RuleDirError(f"no rules.json in {candidate}")
    return candidate.resolve()


class _RulesLoader:
    """Loads the rule catalogue once, on first use, under a lock.

    Lazy on purpose: a misconfigured deployment fails on the first claim instead
    of at import time, and ``GET /v1/health`` can still report why.
    """

    def __init__(self, rules_dir: Path | None) -> None:
        self._explicit = rules_dir
        self._context: RuleContext | None = None
        self._lock = threading.Lock()

    @property
    def rules_dir(self) -> Path:
        return self._explicit if self._explicit is not None else resolve_rules_dir()

    def context(self) -> RuleContext:
        with self._lock:
            if self._context is None:
                self._context = RuleContext.from_rules_dir(self.rules_dir)
            return self._context


def rules_unavailable_detail(exc: RuleDirError) -> str:
    """The body of a catalogue failure: what is wrong, and which setting fixes it.

    The ``RuleDirError`` message names the path that failed; it does not always
    name the environment setting a deployment has to change (a "no rules.json in
    <path>" says nothing about which variable pointed there). This adds that, so
    the operator is never left guessing which variable to set.
    """
    return (
        f"the rule catalogue is unavailable, so this claim cannot be checked: {exc}. "
        f"Point {RULES_DIR_ENV} (or {PACK_ROOT_ENV}) at the pack directory that contains "
        "rules.json, then retry: this is a dependency the service has not been configured "
        "with, not a defect in the submitted claim."
    )


def create_app(
    *,
    store: ReviewStore | None = None,
    rules_dir: str | Path | None = None,
    explain_provider: ExplanationProvider | None = None,
    signer: SessionSigner | None = None,
    directory: ClinicDirectory | None = None,
) -> FastAPI:
    """Build the review API.

    ``store``, ``rules_dir`` and ``explain_provider`` are injectable so tests
    never depend on process environment; in production all three resolve from
    configuration (:func:`claimguard.review.store.resolve_dsn`, which reads
    ``claimguard.config``, for the DSN). ``explain_provider`` defaults to the
    provider the environment configures — the deterministic template when no
    model is configured.

    The handlers themselves are module-level functions that read their
    collaborators from ``request.app.state``, rather than closures registered as
    decorators. Same routes, same behaviour — but they stay directly callable and
    typed, and no function exists only as a decorator target.
    """
    app = FastAPI(
        title="ClaimGuard AI — reviewer workflow",
        version="1.0.0",
        description=(
            "Synthetic claims only. This service reports deterministic check results "
            "and records reviewer decisions; it never approves, denies or submits a claim."
        ),
    )
    app.state.store = store if store is not None else ReviewStore(build_engine())
    app.state.rules = _RulesLoader(None if rules_dir is None else Path(rules_dir))
    app.state.explain = explanation_provider() if explain_provider is None else explain_provider
    app.state.schema_checked = False
    key = os.environ.get("CLAIMGUARD_SESSION_KEY")
    app.state.signer = (
        signer if signer is not None else (SessionSigner(key.encode()) if key else None)
    )
    app.state.directory = (
        directory
        if directory is not None
        else (ClinicDirectory(app.state.store.engine) if app.state.signer is not None else None)
    )

    async def require_clinic_session(request: Request, call_next: Any) -> Response:
        path = request.url.path
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            expected_origin = f"{request.url.scheme}://{request.url.netloc}"
            if (origin and origin != expected_origin) or request.headers.get(
                "sec-fetch-site"
            ) == "cross-site":
                return JSONResponse(
                    status_code=403, content={"detail": "cross-origin clinic action denied"}
                )
        if path in {"/v1/health", "/v1/auth/login"}:
            return cast(Response, await call_next(request))
        active_signer = cast(SessionSigner | None, request.app.state.signer)
        if active_signer is None:
            return JSONResponse(
                status_code=503, content={"detail": "clinic session key is not configured"}
            )
        token = request.cookies.get("claimguard_session")
        if not token:
            return JSONResponse(status_code=401, content={"detail": "clinic sign-in required"})
        try:
            principal = active_signer.resolve(
                token, membership=cast(ClinicDirectory, request.app.state.directory).membership
            )
        except AuthenticationError:
            return JSONResponse(status_code=401, content={"detail": "clinic session is invalid"})
        request.state.principal = principal
        if path.startswith("/review"):
            try:
                authorize(principal, Action.READ_CLAIM, tenant_id=principal.tenant_id)
            except PermissionError:
                return JSONResponse(status_code=403, content={"detail": "access denied"})
        return cast(Response, await call_next(request))

    app.middleware("http")(require_clinic_session)

    app.add_exception_handler(ReviewStoreError, review_error_handler)
    app.add_exception_handler(IllegalReviewTransitionError, review_error_handler)
    app.add_exception_handler(RuleDirError, review_error_handler)
    app.add_api_route("/v1/health", health, methods=["GET"], response_model=HealthResponse)
    app.add_api_route("/v1/auth/login", login, methods=["POST"])
    app.add_api_route("/v1/auth/me", me, methods=["GET"])
    app.add_api_route("/v1/auth/logout", logout, methods=["POST"])
    app.add_api_route(
        "/v1/claims",
        submit_claim,
        methods=["POST"],
        response_model=RunResponse,
        status_code=status.HTTP_201_CREATED,
    )
    app.add_api_route("/v1/runs/{run_id}", get_run, methods=["GET"], response_model=RunResponse)
    app.add_api_route(
        "/v1/runs/{run_id}/claim",
        get_claim,
        methods=["GET"],
        response_model=RunClaimResponse,
    )
    app.add_api_route(
        "/v1/runs/{run_id}/results",
        get_results,
        methods=["GET"],
        response_model=RunResultsResponse,
    )
    app.add_api_route(
        "/v1/runs/{run_id}/decisions",
        record_decision,
        methods=["POST"],
        response_model=DecisionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    app.add_api_route(
        "/v1/runs/{run_id}/decisions",
        list_decisions,
        methods=["GET"],
        response_model=DecisionHistory,
    )
    app.add_api_route("/v1/queue", get_queue, methods=["GET"], response_model=ReviewQueue)
    app.add_api_route("/v1/my-queue", get_my_queue, methods=["GET"], response_model=ReviewQueue)
    app.add_api_route("/v1/assignments", list_assignments, methods=["GET"])
    app.add_api_route("/v1/assignments", assign_claim, methods=["POST"])
    app.add_api_route("/v1/team", list_team, methods=["GET"])
    app.add_api_route("/v1/team", create_team_member, methods=["POST"], status_code=201)
    app.add_api_route("/v1/team/{user_id}/status", set_team_member_status, methods=["POST"])
    app.add_api_route("/v1/departments", list_departments, methods=["GET"])
    app.add_api_route("/v1/departments", create_department, methods=["POST"], status_code=201)
    app.add_api_route("/v1/departments/{department_id}/update", update_department, methods=["POST"])
    app.add_api_route("/v1/operations", operations, methods=["GET"])
    app.add_api_route("/v1/requests", list_requests, methods=["GET"])
    app.add_api_route("/v1/requests", create_request, methods=["POST"], status_code=201)
    app.add_api_route("/v1/requests/{request_id}/resolve", resolve_request, methods=["POST"])
    app.add_api_route("/v1/escalations", list_escalations, methods=["GET"])
    app.add_api_route("/v1/escalations", create_escalation, methods=["POST"], status_code=201)
    app.add_api_route(
        "/v1/escalations/{escalation_id}/resolve", resolve_escalation, methods=["POST"]
    )
    app.add_api_route("/v1/intake-jobs/operations", intake_operations, methods=["GET"])
    app.add_api_route("/v1/intake-jobs", list_intake_jobs, methods=["GET"])
    app.add_api_route("/v1/intake-jobs", create_intake_job, methods=["POST"], status_code=201)
    app.add_api_route("/v1/intake-jobs/{job_id}/submit", submit_intake_job, methods=["POST"])
    app.add_api_route("/v1/intake-jobs/{job_id}", get_intake_job, methods=["GET"])
    app.add_api_route("/v1/activity", activity, methods=["GET"])
    app.add_api_route("/v1/overview", overview, methods=["GET"])
    app.add_api_route("/v1/analytics", analytics, methods=["GET"])
    app.add_api_route("/v1/review-quality", review_quality, methods=["GET"])
    app.add_api_route("/v1/audit", audit, methods=["GET"])
    app.add_api_route("/v1/versions", versions, methods=["GET"])
    app.add_api_route("/v1/redacted-logs", redacted_logs, methods=["GET"])
    app.add_api_route("/v1/audit-integrity", audit_integrity, methods=["GET"])
    app.add_api_route("/v1/configuration", configuration, methods=["GET"])
    app.add_api_route("/v1/configuration", set_configuration, methods=["POST"])
    app.add_api_route(
        "/v1/claims/{claim_id}/recheck",
        recheck,
        methods=["POST"],
        response_model=RunResponse,
        status_code=status.HTTP_201_CREATED,
    )
    app.include_router(review_ui.router)
    return app


# ---------------------------------------------------------------------------
# Handlers (registered by create_app; module-level so they are plain functions)
# ---------------------------------------------------------------------------


def review_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map a review failure to an HTTP status, with the failure named in the body.

    Registered for :class:`ReviewStoreError`,
    :class:`IllegalReviewTransitionError` and :class:`RuleDirError`; the ``else``
    arm cannot be reached through routing but keeps the function total.
    """
    if isinstance(exc, RuleDirError):
        return JSONResponse(
            status_code=RULES_UNAVAILABLE_STATUS,
            content={"detail": rules_unavailable_detail(exc), "error": type(exc).__name__},
        )
    if isinstance(exc, IllegalReviewTransitionError):
        status_code = status.HTTP_409_CONFLICT
    elif isinstance(exc, ReviewStoreError):
        status_code = _error_status(exc)
    else:  # pragma: no cover - only registered for the review error families
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return JSONResponse(
        status_code=status_code,
        content={"detail": str(exc), "error": type(exc).__name__},
    )


def health(request: Request) -> HealthResponse:
    """Readiness: which schema the store sees and whether the catalogue loaded."""
    review_store = _store_of(request)
    rules = _rules_of(request.app)
    revision: str | None = None
    database = "unreachable"
    try:
        revision = review_store.schema_revision()
        if revision == SCHEMA_REVISION:
            review_store.ensure_schema()
            database = "ready"
        else:
            database = "schema-missing"
    except SchemaNotMigratedError:
        database = "schema-missing"
    except Exception as exc:  # noqa: BLE001 - readiness reporting must not raise
        database = f"unreachable: {type(exc).__name__}"
    rules_ready = True
    rules_dir: str | None = None
    try:
        rules.context()
        rules_dir = str(rules.rules_dir)
    except RuleDirError:
        rules_ready = False
    return HealthResponse(
        status="ok"
        if database == "ready" and rules_ready and request.app.state.signer
        else "degraded",
        database=database,
        schema_revision=revision,
        rules_dir=rules_dir,
        rules_ready=rules_ready,
        engine_rule_version=RULE_VERSION,
    )


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str
    tenant_id: str


def login(request: Request, response: Response, payload: LoginRequest) -> dict[str, str]:
    active_signer = cast(SessionSigner | None, request.app.state.signer)
    if active_signer is None:
        raise HTTPException(status_code=503, detail="clinic session key is not configured")
    principal = cast(ClinicDirectory, request.app.state.directory).authenticate(
        payload.email, payload.password, payload.tenant_id
    )
    if principal is None:
        raise HTTPException(status_code=401, detail="invalid clinic credentials")
    token = active_signer.issue(principal.user_id, principal.tenant_id)
    response.set_cookie(
        "claimguard_session",
        token,
        max_age=8 * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return {
        "user_id": principal.user_id,
        "tenant_id": principal.tenant_id,
        "role": principal.role.value,
    }


def me(request: Request) -> dict[str, str]:
    principal = cast(Principal, request.state.principal)
    return {
        "user_id": principal.user_id,
        "tenant_id": principal.tenant_id,
        "role": principal.role.value,
    }


def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie("claimguard_session", path="/")
    return {"signed_out": True}


def submit_claim(request: Request, payload: SubmitClaimRequest) -> RunResponse:
    """Validate one envelope, run the 15 checks and persist the run."""
    review_store = _migrated_store(request, Action.CREATE_CLAIM)
    records = _evaluate(request.app, payload.claim)
    explained = _explain(request.app, records, payload.claim)
    recorded = review_store.record_run(
        dict(payload.claim),
        explained.records,
        rule_version=RULE_VERSION,
        model_version=explained.model_version,
        prompt_version=explained.prompt_version,
        initiated_by=cast(Principal, request.state.principal).user_id,
        explanations=explained.provenance,
    )
    return _run_response(recorded)


def get_run(request: Request, run_id: str) -> RunResponse:
    """One run's identity, versions, counts and audit stamp."""
    review_store = _claim_store(request, run_id, Action.READ_CLAIM)
    run = review_store.get_run(run_id)
    if run is None:
        raise RunNotFoundError(f"unknown run: {run_id}")
    return _status_response(
        run, review_store.get_results(run_id), review_store.run_audit_stamp(run_id)
    )


def get_results(request: Request, run_id: str) -> RunResultsResponse:
    """The run's 15 records, exactly as the CLI emits them, with their provenance."""
    review_store = _claim_store(request, run_id, Action.READ_CLAIM)
    run = review_store.get_run(run_id)
    if run is None:
        raise RunNotFoundError(f"unknown run: {run_id}")
    return RunResultsResponse(
        run=run,
        results=review_store.get_results(run_id),
        explanations=review_store.get_explanations(run_id),
    )


def get_claim(request: Request, run_id: str) -> RunClaimResponse:
    """The run's immutable synthetic claim input, for drafting a new version."""
    review_store = _claim_store(request, run_id, Action.READ_CLAIM)
    run = review_store.get_run(run_id)
    if run is None:
        raise RunNotFoundError(f"unknown run: {run_id}")
    envelope = review_store.get_claim_envelope(run_id)
    if envelope is None:
        raise RunNotFoundError(f"unknown run: {run_id}")
    return RunClaimResponse(
        run_id=run.run_id,
        claim_id=run.claim_id,
        version=run.version,
        claim=envelope,
    )


def get_queue(
    request: Request,
    # ``status`` is the pack's word for a rule status: the parameter is named for
    # the filter it applies, and aliased so the wire name stays ``status``.
    status_filter: Annotated[Status | None, Query(alias="status")] = None,
    severity: Severity | None = None,
    rule_id: str | None = None,
    claim_id: str | None = None,
    include_all: bool = False,
) -> ReviewQueue:
    """The review queue: filtered findings with unresolved-check counts."""
    filters = QueueFilters(
        status=status_filter,
        severity=severity,
        rule_id=rule_id,
        claim_id=claim_id,
        include_all=include_all,
    )
    return _migrated_store(request, Action.ASSIGN_CLAIM).queue(filters)


def get_my_queue(request: Request) -> ReviewQueue:
    """The signed-in reviewer's assigned claims only."""
    principal = cast(Principal, request.state.principal)
    review_store = _migrated_store(request, Action.READ_QUEUE)
    claim_ids = AssignmentStore(review_store.engine).visible_claim_ids(
        principal.tenant_id, principal.user_id
    )
    return review_store.queue_for_claim_ids(claim_ids, QueueFilters(include_all=True))


class AssignClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    reviewer_user_id: str


def list_assignments(request: Request) -> list[Assignment]:
    principal = cast(Principal, request.state.principal)
    review_store = _migrated_store(request, Action.ASSIGN_CLAIM)
    return AssignmentStore(review_store.engine).list_assignments(principal.tenant_id)


def assign_claim(request: Request, payload: AssignClaimRequest) -> Assignment:
    principal = cast(Principal, request.state.principal)
    review_store = _migrated_store(request, Action.ASSIGN_CLAIM)
    try:
        return AssignmentStore(review_store.engine).assign(
            principal.tenant_id,
            payload.claim_id,
            payload.reviewer_user_id,
            assigned_by=principal.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def list_team(request: Request, include_inactive: bool = False) -> list[TeamMember]:
    principal = cast(Principal, request.state.principal)
    _migrated_store(request, Action.MANAGE_TEAM if include_inactive else Action.ASSIGN_CLAIM)
    return cast(ClinicDirectory, request.app.state.directory).team(
        principal.tenant_id, include_inactive=include_inactive
    )


class CreateTeamMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    display_name: str | None = None
    password: str
    role: Role


def create_team_member(request: Request, payload: CreateTeamMemberRequest) -> TeamMember:
    principal = cast(Principal, request.state.principal)
    _migrated_store(request, Action.MANAGE_TEAM)
    try:
        return cast(ClinicDirectory, request.app.state.directory).add_member(
            principal.tenant_id,
            email=payload.email,
            display_name=payload.display_name,
            password=payload.password,
            role=payload.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class SetMemberStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool


def set_team_member_status(
    request: Request, user_id: str, payload: SetMemberStatusRequest
) -> TeamMember:
    principal = cast(Principal, request.state.principal)
    _migrated_store(request, Action.MANAGE_TEAM)
    try:
        return cast(ClinicDirectory, request.app.state.directory).set_membership_active(
            principal.tenant_id, user_id, payload.active
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def list_departments(request: Request) -> list[Department]:
    principal = cast(Principal, request.state.principal)
    _migrated_store(request, Action.MANAGE_TEAM)
    return cast(ClinicDirectory, request.app.state.directory).departments(principal.tenant_id)


class CreateDepartmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


def create_department(request: Request, payload: CreateDepartmentRequest) -> Department:
    principal = cast(Principal, request.state.principal)
    _migrated_store(request, Action.MANAGE_TEAM)
    try:
        return cast(ClinicDirectory, request.app.state.directory).add_department(
            principal.tenant_id, payload.name
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class UpdateDepartmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    active: bool


def update_department(
    request: Request, department_id: str, payload: UpdateDepartmentRequest
) -> Department:
    principal = cast(Principal, request.state.principal)
    _migrated_store(request, Action.MANAGE_TEAM)
    try:
        return cast(ClinicDirectory, request.app.state.directory).update_department(
            principal.tenant_id, department_id, name=payload.name, active=payload.active
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def operations(request: Request) -> dict[str, str | bool | None]:
    """Claim-blind service readiness for technical staff."""
    principal = cast(Principal, request.state.principal)
    try:
        authorize(principal, Action.READ_OPERATIONS, tenant_id=principal.tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="access denied") from exc
    result = health(request)
    return {
        "status": result.status,
        "database": result.database,
        "schema_revision": result.schema_revision,
        "rules_ready": result.rules_ready,
        "engine_rule_version": result.engine_rule_version,
    }


def _workspaces(request: Request, action: Action) -> tuple[Principal, WorkspaceStore]:
    principal = cast(Principal, request.state.principal)
    review_store = _migrated_store(request, action)
    return principal, WorkspaceStore(review_store.engine)


class CreateRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    message: str


class ResolveRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response: str


def list_requests(request: Request) -> list[dict[str, Any]]:
    principal, work = _workspaces(request, Action.READ_CLAIM)
    return work.requests(principal.tenant_id, _reviewer_visible_claims(request))


def create_request(request: Request, payload: CreateRequestPayload) -> dict[str, Any]:
    principal, work = _workspaces(request, Action.READ_CLAIM)
    _claim_store(request, payload.run_id, Action.READ_CLAIM)
    if not payload.message.strip():
        raise HTTPException(status_code=422, detail="request message is required")
    try:
        return work.create_request(
            principal.tenant_id, payload.run_id, payload.message.strip(), principal.user_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def resolve_request(
    request: Request, request_id: str, payload: ResolveRequestPayload
) -> dict[str, Any]:
    principal, work = _workspaces(request, Action.READ_CLAIM)
    if not payload.response.strip():
        raise HTTPException(status_code=422, detail="response is required")
    resolved = work.resolve_request(
        principal.tenant_id,
        request_id,
        payload.response.strip(),
        principal.user_id,
        _reviewer_visible_claims(request),
    )
    if resolved is None:
        raise HTTPException(status_code=404, detail="open request not found in this clinic")
    return resolved


class CreateEscalationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    reason: str


class ResolveEscalationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: str


def list_escalations(request: Request) -> list[dict[str, Any]]:
    principal, work = _workspaces(request, Action.ASSIGN_CLAIM)
    return work.escalations(principal.tenant_id)


def create_escalation(request: Request, payload: CreateEscalationPayload) -> dict[str, Any]:
    principal, work = _workspaces(request, Action.ASSIGN_CLAIM)
    if not payload.reason.strip():
        raise HTTPException(status_code=422, detail="escalation reason is required")
    try:
        return work.create_escalation(
            principal.tenant_id, payload.run_id, payload.reason.strip(), principal.user_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def resolve_escalation(
    request: Request, escalation_id: str, payload: ResolveEscalationPayload
) -> dict[str, Any]:
    principal, work = _workspaces(request, Action.ASSIGN_CLAIM)
    if not payload.resolution.strip():
        raise HTTPException(status_code=422, detail="resolution is required")
    resolved = work.resolve_escalation(
        principal.tenant_id, escalation_id, payload.resolution.strip(), principal.user_id
    )
    if resolved is None:
        raise HTTPException(status_code=404, detail="open escalation not found in this clinic")
    return resolved


class IntakePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str
    content: str = ""
    source_format: Literal["envelope_json", "csv_split", "fhir_bundle"] = "envelope_json"
    files: dict[str, str] | None = None
    sidecar: dict[str, Any] | None = None


def list_intake_jobs(request: Request) -> list[dict[str, Any]]:
    principal, work = _workspaces(request, Action.READ_CLAIM)
    return work.intake_jobs(
        principal.tenant_id,
        submitted_by=principal.user_id if principal.role is Role.RCM_REVIEWER else None,
        allowed_claim_ids=_reviewer_visible_claims(request),
    )


def create_intake_job(request: Request, payload: IntakePayload) -> dict[str, Any]:
    principal, work = _workspaces(request, Action.CREATE_CLAIM)
    try:
        return work.create_intake_job(
            principal.tenant_id,
            principal.user_id,
            payload.filename,
            payload.content,
            source_format=payload.source_format,
            files=payload.files,
            sidecar=payload.sidecar,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def get_intake_job(request: Request, job_id: str) -> dict[str, Any]:
    principal, work = _workspaces(request, Action.READ_CLAIM)
    job = work.intake_job(
        principal.tenant_id,
        job_id,
        submitted_by=principal.user_id if principal.role is Role.RCM_REVIEWER else None,
        allowed_claim_ids=_reviewer_visible_claims(request),
    )
    if job is None:
        raise HTTPException(status_code=404, detail="intake job not found in this clinic")
    return job


def submit_intake_job(request: Request, job_id: str) -> RunResponse:
    principal, work = _workspaces(request, Action.CREATE_CLAIM)

    def check_draft(draft: dict[str, Any]) -> tuple[str, RunResponse]:
        records = _evaluate(request.app, draft)
        explained = _explain(request.app, records, draft)
        recorded = _migrated_store(request, Action.CREATE_CLAIM).record_run(
            draft,
            explained.records,
            rule_version=RULE_VERSION,
            model_version=explained.model_version,
            prompt_version=explained.prompt_version,
            initiated_by=principal.user_id,
            explanations=explained.provenance,
        )
        return recorded.run.run_id, _run_response(recorded)

    try:
        return work.submit_intake_job(
            principal.tenant_id,
            job_id,
            principal.user_id if principal.role is Role.RCM_REVIEWER else None,
            check_draft,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def activity(request: Request) -> list[dict[str, Any]]:
    principal, work = _workspaces(request, Action.READ_CLAIM)
    return work.activity(principal.tenant_id, _reviewer_visible_claims(request))


def overview(request: Request) -> dict[str, Any]:
    principal, work = _workspaces(request, Action.READ_ANALYTICS)
    return work.overview(principal.tenant_id)


def analytics(request: Request) -> dict[str, Any]:
    principal, work = _workspaces(request, Action.READ_ANALYTICS)
    return work.analytics(principal.tenant_id)


def review_quality(request: Request) -> dict[str, Any]:
    principal, work = _workspaces(request, Action.READ_ANALYTICS)
    return work.review_quality(principal.tenant_id)


def audit(request: Request) -> list[dict[str, Any]]:
    principal, work = _workspaces(request, Action.READ_AUDIT)
    return work.audit(principal.tenant_id)


def intake_operations(request: Request) -> dict[str, Any]:
    principal, work = _workspaces(request, Action.READ_OPERATIONS)
    return work.intake_operations(principal.tenant_id)


def versions(request: Request) -> dict[str, Any]:
    principal, work = _workspaces(request, Action.READ_OPERATIONS)
    return {
        "active_rule_version": RULE_VERSION,
        "active_explanation_provider": type(_provider_of(request.app)).__name__,
        "observed_versions": work.versions(principal.tenant_id),
    }


def redacted_logs(request: Request) -> list[dict[str, Any]]:
    principal, work = _workspaces(request, Action.READ_OPERATIONS)
    return work.redacted_logs(principal.tenant_id)


def audit_integrity(request: Request) -> dict[str, Any]:
    principal, work = _workspaces(request, Action.READ_OPERATIONS)
    return work.audit_integrity(principal.tenant_id)


def configuration(request: Request) -> dict[str, bool]:
    principal, work = _workspaces(request, Action.READ_OPERATIONS)
    return work.configuration(principal.tenant_id)


class ConfigurationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intake_enabled: bool


def set_configuration(request: Request, payload: ConfigurationPayload) -> dict[str, bool]:
    principal, work = _workspaces(request, Action.MANAGE_OPERATIONS)
    return work.set_configuration(principal.tenant_id, principal.user_id, payload.intake_enabled)


def record_decision(request: Request, run_id: str, payload: DecisionRequest) -> DecisionResponse:
    """Append one reviewer decision to the ledger and report the new state."""
    principal = cast(Principal, request.state.principal)
    if payload.actor != principal.user_id:
        raise HTTPException(status_code=403, detail="decision actor must match signed-in user")
    recorded = _claim_store(request, run_id, Action.RECORD_DECISION).record_decision(
        run_id, payload
    )
    return DecisionResponse(
        decision=recorded.decision, review=recorded.review, audit=recorded.audit
    )


def list_decisions(request: Request, run_id: str) -> DecisionHistory:
    """Every decision recorded against a run, oldest first."""
    review_store = _claim_store(request, run_id, Action.READ_CLAIM)
    if review_store.get_run(run_id) is None:
        raise RunNotFoundError(f"unknown run: {run_id}")
    return review_store.decision_history(run_id)


def recheck(request: Request, claim_id: str, payload: RecheckRequest) -> RunResponse:
    """Evaluate a corrected envelope as a NEW version of the claim."""
    principal = cast(Principal, request.state.principal)
    if payload.actor != principal.user_id:
        raise HTTPException(status_code=403, detail="recheck actor must match signed-in user")
    review_store = _migrated_store(request, Action.RECHECK_CLAIM)
    if review_store.latest_run(claim_id) is None:
        raise RunNotFoundError(f"claim {claim_id!r} has no run to recheck")
    if principal.role is Role.RCM_REVIEWER and not AssignmentStore(review_store.engine).can_review(
        principal.tenant_id, claim_id, principal.user_id
    ):
        raise HTTPException(status_code=403, detail="claim is not assigned to this reviewer")
    envelope = payload.claim
    if envelope.get("claim_id") != claim_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"the corrected envelope is for {envelope.get('claim_id')!r}, not {claim_id!r}",
        )
    records = _evaluate(request.app, envelope)
    explained = _explain(request.app, records, envelope)
    recorded = review_store.record_recheck(
        dict(envelope),
        explained.records,
        rule_version=RULE_VERSION,
        model_version=explained.model_version,
        prompt_version=explained.prompt_version,
        initiated_by=payload.actor,
        explanations=explained.provenance,
    )
    return _run_response(recorded)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store_of(request: Request) -> ReviewStore:
    """The app's review store (``create_app`` always installs one)."""
    return cast(ReviewStore, request.app.state.store)


def _reviewer_visible_claims(request: Request) -> list[str] | None:
    principal = cast(Principal, request.state.principal)
    if principal.role is not Role.RCM_REVIEWER:
        return None
    return AssignmentStore(_store_of(request).engine).visible_claim_ids(
        principal.tenant_id, principal.user_id
    )


def _claim_store(request: Request, run_id: str, action: Action) -> ReviewStore:
    review_store = _migrated_store(request, action)
    run = review_store.get_run(run_id)
    if run is None:
        raise RunNotFoundError(f"unknown run: {run_id}")
    principal = cast(Principal, request.state.principal)
    if principal.role is Role.RCM_REVIEWER and not AssignmentStore(review_store.engine).can_review(
        principal.tenant_id, run.claim_id, principal.user_id
    ):
        raise HTTPException(status_code=403, detail="claim is not assigned to this reviewer")
    return review_store


def _rules_of(app: FastAPI) -> _RulesLoader:
    """The app's lazily-loaded rule catalogue loader."""
    return cast(_RulesLoader, app.state.rules)


def _provider_of(app: FastAPI) -> ExplanationProvider:
    """The app's explanation provider (``create_app`` always installs one)."""
    return cast(ExplanationProvider, app.state.explain)


def _explain(
    app: FastAPI, records: Sequence[ResultRecord], envelope: Mapping[str, Any]
) -> ExplainedRun:
    """Produce the reviewer-facing explanations for a run, with their provenance.

    The engine's records go in and the same 15 records come back with
    ``explanation`` replaced where the bounded explanation layer rewrote it;
    everything else is copied through and re-validated against the engine's own
    15-key model (see :func:`claimguard.review.explanations.explain_run`). The
    claim's untrusted free text is deliberately not forwarded to a model.

    The catalogue is read through the same loader the engine uses, so a
    misconfigured deployment fails here exactly as it does a few lines earlier —
    with the structured 503 that names the setting to fix.
    """
    return explain_run(
        records,
        _rules_of(app).context(),
        envelope,
        provider=_provider_of(app),
    )


def _migrated_store(request: Request, action: Action) -> ReviewStore:
    """The app's store, once its schema is known to be applied.

    Checked on the first request and remembered, so a deployment that forgot
    ``alembic upgrade head`` gets a 503 naming the command instead of a 500
    from a missing relation, and steady-state requests pay nothing for it.
    """
    principal = cast(Principal, request.state.principal)
    try:
        authorize(principal, action, tenant_id=principal.tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="access denied") from exc
    review_store = cast(ReviewStore, request.app.state.store)
    if not request.app.state.schema_checked:
        review_store.ensure_schema()
        request.app.state.schema_checked = True
    return review_store.for_tenant(principal.tenant_id)


def _error_status(exc: ReviewStoreError) -> int:
    if isinstance(exc, RunNotFoundError | FindingNotFoundError):
        return status.HTTP_404_NOT_FOUND
    if isinstance(exc, SchemaNotMigratedError):
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if isinstance(exc, RunSupersededError | NoCorrectionError):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


def _evaluate(app: FastAPI, payload: Mapping[str, Any]) -> list[ResultRecord]:
    """Validate the transport envelope, then run the 15 checks over the ORIGINAL object.

    The engine reads the submitted object (never a re-coerced model), so evidence
    pointers keep resolving against what the caller actually sent. Every record is
    then checked against that same object by the engine's own contract validator
    (evidence re-resolves, affected line ids exist, key set is exact). A transport
    defect is 422 with the engine's own wording — the same text the CLI quarantines.
    """
    try:
        validate_transport(payload)
        envelope: Claim = payload
        records = [
            validate_record(record, envelope)
            for record in evaluate_claim(envelope, app.state.rules.context())
        ]
    except (TransportError, ContractError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if len(records) != 15:  # pragma: no cover - the engine's coverage contract
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"the engine produced {len(records)} records, expected 15",
        )
    return records


def _run_response(recorded: RecordedRun) -> RunResponse:
    return _status_response(recorded.run, recorded.results, recorded.audit, recorded.duplicate)


def _status_response(
    run: Any,
    results: Sequence[ResultRecord],
    audit: AuditStamp,
    duplicate: bool = False,
) -> RunResponse:
    return RunResponse(
        run=run,
        results=len(results),
        needs_attention=sum(1 for record in results if requires_attention(record)),
        by_status=summarize_statuses(results),
        duplicate=duplicate,
        audit=audit,
    )


app = create_app()
