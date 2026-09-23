"""FastAPI surface for the reviewer workflow (MVP behaviours 4, 5 and 7).

WHAT THIS SURFACE IS
--------------------
Seven honest operations, and nothing that decides anything about a claim:

=====================================  ==============================================
``POST /v1/claims``                    validate the envelope, run the 15 checks,
                                       persist the run and its audit event
``GET  /v1/runs/{run_id}``             one run's identity, versions and provenance
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
from typing import Annotated, Any, Final, cast

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

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
    RunResponse,
    RunResultsResponse,
    SubmitClaimRequest,
    requires_attention,
    summarize_statuses,
)
from claimguard.review.store import (
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

#: Who initiated a run when the caller is the submission surface itself.
SUBMIT_ACTOR: Final = "api-submit"

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

    app.add_exception_handler(ReviewStoreError, review_error_handler)
    app.add_exception_handler(IllegalReviewTransitionError, review_error_handler)
    app.add_exception_handler(RuleDirError, review_error_handler)
    app.add_api_route("/v1/health", health, methods=["GET"], response_model=HealthResponse)
    app.add_api_route(
        "/v1/claims",
        submit_claim,
        methods=["POST"],
        response_model=RunResponse,
        status_code=status.HTTP_201_CREATED,
    )
    app.add_api_route("/v1/runs/{run_id}", get_run, methods=["GET"], response_model=RunResponse)
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
        database = "ready" if revision is not None else "schema-missing"
    except Exception as exc:  # noqa: BLE001 - readiness reporting must not raise
        database = f"unreachable: {type(exc).__name__}"
    rules_ready = True
    try:
        rules.context()
    except RuleDirError:
        rules_ready = False
    return HealthResponse(
        status="ok" if database == "ready" and rules_ready else "degraded",
        database=database,
        schema_revision=revision,
        rules_dir=str(rules.rules_dir),
        rules_ready=rules_ready,
        engine_rule_version=RULE_VERSION,
    )


def submit_claim(request: Request, payload: SubmitClaimRequest) -> RunResponse:
    """Validate one envelope, run the 15 checks and persist the run."""
    review_store = _migrated_store(request.app)
    records = _evaluate(request.app, payload.claim)
    explained = _explain(request.app, records, payload.claim)
    recorded = review_store.record_run(
        dict(payload.claim),
        explained.records,
        rule_version=RULE_VERSION,
        model_version=explained.model_version,
        prompt_version=explained.prompt_version,
        initiated_by=SUBMIT_ACTOR,
        explanations=explained.provenance,
    )
    return _run_response(recorded)


def get_run(request: Request, run_id: str) -> RunResponse:
    """One run's identity, versions, counts and audit stamp."""
    review_store = _migrated_store(request.app)
    run = review_store.get_run(run_id)
    if run is None:
        raise RunNotFoundError(f"unknown run: {run_id}")
    return _status_response(
        run, review_store.get_results(run_id), review_store.run_audit_stamp(run_id)
    )


def get_results(request: Request, run_id: str) -> RunResultsResponse:
    """The run's 15 records, exactly as the CLI emits them, with their provenance."""
    review_store = _migrated_store(request.app)
    run = review_store.get_run(run_id)
    if run is None:
        raise RunNotFoundError(f"unknown run: {run_id}")
    return RunResultsResponse(
        run=run,
        results=review_store.get_results(run_id),
        explanations=review_store.get_explanations(run_id),
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
    return _migrated_store(request.app).queue(filters)


def record_decision(request: Request, run_id: str, payload: DecisionRequest) -> DecisionResponse:
    """Append one reviewer decision to the ledger and report the new state."""
    recorded = _migrated_store(request.app).record_decision(run_id, payload)
    return DecisionResponse(
        decision=recorded.decision, review=recorded.review, audit=recorded.audit
    )


def list_decisions(request: Request, run_id: str) -> DecisionHistory:
    """Every decision recorded against a run, oldest first."""
    review_store = _migrated_store(request.app)
    if review_store.get_run(run_id) is None:
        raise RunNotFoundError(f"unknown run: {run_id}")
    return review_store.decision_history(run_id)


def recheck(request: Request, claim_id: str, payload: RecheckRequest) -> RunResponse:
    """Evaluate a corrected envelope as a NEW version of the claim."""
    review_store = _migrated_store(request.app)
    if review_store.latest_run(claim_id) is None:
        raise RunNotFoundError(f"claim {claim_id!r} has no run to recheck")
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


def _migrated_store(app: FastAPI) -> ReviewStore:
    """The app's store, once its schema is known to be applied.

    Checked on the first request and remembered, so a deployment that forgot
    ``alembic upgrade head`` gets a 503 naming the command instead of a 500
    from a missing relation, and steady-state requests pay nothing for it.
    """
    review_store = cast(ReviewStore, app.state.store)
    if not app.state.schema_checked:
        review_store.ensure_schema()
        app.state.schema_checked = True
    return review_store


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
