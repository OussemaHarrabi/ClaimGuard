"""PostgreSQL persistence for the review workflow (MVP behaviours 4, 5, 7).

WHAT THIS MODULE OWNS
---------------------
The four tables migration ``0002_review_workflow.sql`` and ``0003`` create, and
the queries the reviewer surface needs over them:

*   :meth:`ReviewStore.record_run` — persist one engine run (claim version, input
    hash, versions, the 15 records, the explanation provenance) **and** its audit
    event, in one transaction.
*   :meth:`ReviewStore.record_recheck` — persist a correction as a NEW claim
    version that supersedes the previous run. The previous run's row, records and
    decisions are untouched, and the database refuses to update them
    (``trg_rule_runs_no_update`` / ``trg_rule_results_no_update``).
*   :meth:`ReviewStore.get_explanations` — how each record's reviewer-facing
    explanation was produced, from the ``run_explanations`` sidecar. The 15-key
    record has no room for a sixteenth key, so provenance lives beside it.
*   :meth:`ReviewStore.queue` — the current review queue, with filters and
    unresolved-check counts.
*   :meth:`ReviewStore.record_decision` — append a reviewer decision (the pack's
    four actions), checking the decision state machine, the 7-key event contract
    and the audit chain, in one transaction.

WHAT THIS MODULE DOES NOT DO
----------------------------
It stores exactly the records it is handed. Producing the reviewer-facing
explanation — and the provenance that goes with it — is the API's job
(:mod:`claimguard.review.explanations`); a store that rewrote a record on the way
in would make "the engine's output" unverifiable, so it never does.

CONVENTIONS IT RESPECTS
-----------------------
*   **The DSN comes from** :func:`claimguard.config.get_settings` — the same
    single source of truth ``claimguard/db/migrations/env.py`` uses. There is no
    second connection string anywhere in this package.
*   **Every connection runs with ``TimeZone=UTC``.** The audit trigger hashes
    ``at::text``, which renders in the session time zone; without UTC the trigger
    and :func:`claimguard.audit.chain.chain_hash` disagree on every row. The
    ``-c timezone=UTC`` server option is used rather than a ``SET`` statement
    because SQLAlchemy's pool resets a connection on check-in (rolling back a
    session-level ``SET``).
*   **Migration 0001 is untouched.** This module only reads
    ``claimguard.audit_events`` (through :mod:`claimguard.review.audit_events`)
    and never writes any other pre-existing table.
*   **Nothing here adjudicates.** A run is a check result set; a decision is a
    reviewer's note about one check. There is no approve/deny/pay code path.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import (
    Column,
    ColumnElement,
    MetaData,
    Select,
    Table,
    Text,
    and_,
    func,
    insert,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.types import BOOLEAN, INTEGER, NUMERIC, TIMESTAMP

from claimguard.config import get_settings
from claimguard.edu.envelope import RULE_IDS, ResultRecord, Status
from claimguard.review import audit_events
from claimguard.review.models import (
    ACTION_STATUS,
    AuditStamp,
    ClaimQueueSummary,
    DecisionHistory,
    DecisionHistoryEntry,
    DecisionRequest,
    ExplanationProvenance,
    FindingView,
    QueueCounts,
    QueueFilters,
    ReviewDecisionEvent,
    ReviewQueue,
    ReviewState,
    RuleRun,
    StoredDecision,
    next_status,
    requires_attention,
    summarize_statuses,
)

#: The Alembic revision this module's tables come from.
SCHEMA_REVISION: Final = "0011"

#: ``run_id`` prefix (opaque; deliberately carries no claim identifier).
RUN_ID_PREFIX: Final = "RUN-"

#: Namespace for transaction-scoped advisory locks that serialize writes to one
#: claim. PostgreSQL hashes the full key to a signed bigint; the namespace keeps
#: these locks distinct from the audit chain's project-wide lock.
CLAIM_WRITE_LOCK_NAMESPACE: Final = "claimguard:review:claim:"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ReviewStoreError(RuntimeError):
    """Base class for review-store failures the HTTP layer maps to a status code."""


class SchemaNotMigratedError(ReviewStoreError):
    """The review tables are absent: ``alembic upgrade head`` has not been run."""


class RunNotFoundError(ReviewStoreError):
    """No such run."""


class FindingNotFoundError(ReviewStoreError):
    """No such rule result on that run."""


class RunSupersededError(ReviewStoreError):
    """The run has been replaced by a newer claim version."""


class NoCorrectionError(ReviewStoreError):
    """A recheck was asked for but the submitted envelope is byte-identical."""


# ---------------------------------------------------------------------------
# Schema mapping (read + write; migrations remain the authority)
# ---------------------------------------------------------------------------

_REVIEW_METADATA = MetaData()

RUNS = Table(
    "rule_runs",
    _REVIEW_METADATA,
    Column("run_id", Text, primary_key=True),
    Column("tenant_id", Text, nullable=False),
    Column("claim_id", Text, nullable=False),
    Column("version", INTEGER, nullable=False),
    Column("supersedes_run_id", Text),
    Column("input_hash", Text, nullable=False),
    Column("envelope", JSONB, nullable=False),
    Column("trace_id", Text, nullable=False),
    Column("rule_version", Text, nullable=False),
    Column("model_version", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("initiated_by", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
    schema="claimguard",
)

RESULTS = Table(
    "rule_results",
    _REVIEW_METADATA,
    Column("run_id", Text, nullable=False),
    Column("tenant_id", Text, nullable=False),
    Column("claim_id", Text, nullable=False),
    Column("seq", INTEGER, nullable=False),
    Column("rule_id", Text, nullable=False),
    Column("rule_version", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("severity", Text, nullable=False),
    Column("affected_line_ids", ARRAY(Text), nullable=False),
    Column("evidence", JSONB, nullable=False),
    Column("rule_source", Text, nullable=False),
    Column("explanation", Text, nullable=False),
    Column("corrective_action", Text, nullable=False),
    Column[Decimal | None]("confidence", NUMERIC),
    Column("confidence_kind", Text, nullable=False),
    Column("requires_human_review", BOOLEAN, nullable=False),
    Column("method", Text, nullable=False),
    Column("review_status", Text, nullable=False),
    schema="claimguard",
)

DECISIONS = Table(
    "review_decisions",
    _REVIEW_METADATA,
    Column("decision_id", UUID(as_uuid=True), primary_key=True),
    Column("seq", INTEGER, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("tenant_id", Text, nullable=False),
    Column("claim_id", Text, nullable=False),
    Column("rule_id", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("actor", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("original_status", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
    schema="claimguard",
)

#: The explanation-provenance sidecar (migration 0003). One row per result
#: record of a run: the 15-key record itself has no room for a sixteenth key, so
#: "which text was model-assisted, and why did a fallback stand in" lives here,
#: keyed by the same ``(run_id, rule_id)`` the results use.
EXPLANATIONS = Table(
    "run_explanations",
    _REVIEW_METADATA,
    Column("run_id", Text, nullable=False),
    Column("tenant_id", Text, nullable=False),
    Column("rule_id", Text, nullable=False),
    Column("seq", INTEGER, nullable=False),
    Column("source", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("rewritten", BOOLEAN, nullable=False),
    Column("fallback_used", BOOLEAN, nullable=False),
    Column("correction_recommendation", Text, nullable=False),
    Column("cited_evidence_paths", JSONB, nullable=False),
    Column("security_decision", Text, nullable=False),
    Column("receipt_sha256", Text),
    Column("rejection_reasons", JSONB, nullable=False),
    Column("declined_reason", Text),
    schema="claimguard",
)

#: The provenance columns, in the order the API serves them.
_EXPLANATION_COLUMNS: Final[tuple[str, ...]] = (
    "rule_id",
    "seq",
    "source",
    "provider",
    "rewritten",
    "fallback_used",
    "correction_recommendation",
    "cited_evidence_paths",
    "security_decision",
    "receipt_sha256",
    "rejection_reasons",
    "declined_reason",
)

#: Tables required before the review API serves requests (migrations 0002-0005).
#: ``ensure_schema`` refuses a database missing the clinic directory too.
REQUIRED_TABLES: Final[tuple[str, ...]] = (
    "rule_runs",
    "rule_results",
    "review_decisions",
    "run_explanations",
    "clinics",
    "users",
    "clinic_memberships",
    "clinic_departments",
    "claim_assignments",
    "clinic_requests",
    "clinic_escalations",
    "intake_jobs",
    "clinic_configuration",
)


def _table_present(connection: Connection, name: str) -> bool:
    """True when ``claimguard.<name>`` exists in the connected database."""
    return bool(
        connection.execute(
            text("SELECT to_regclass(:qualified) IS NOT NULL"), {"qualified": f"claimguard.{name}"}
        ).scalar()
    )


#: The result columns, in the pack's key order (record reconstruction).
_RESULT_COLUMNS: Final[tuple[str, ...]] = (
    "claim_id",
    "rule_id",
    "rule_version",
    "status",
    "severity",
    "affected_line_ids",
    "evidence",
    "rule_source",
    "explanation",
    "corrective_action",
    "confidence",
    "confidence_kind",
    "requires_human_review",
    "method",
    "review_status",
)


# ---------------------------------------------------------------------------
# Engine / DSN
# ---------------------------------------------------------------------------


def resolve_dsn() -> str:
    """The review store's DSN — ``claimguard.config`` is the single source of truth."""
    return get_settings().database_url


def build_engine(dsn: str | None = None) -> Engine:
    """Create the review engine, pinned to UTC (the audit chain depends on it)."""
    url = dsn if dsn is not None else resolve_dsn()
    return create_engine(url)


def create_engine(url: str) -> Engine:
    """Build a SQLAlchemy engine for ``url`` with the workflow's conventions."""
    from sqlalchemy import create_engine as sa_create_engine

    return sa_create_engine(
        url,
        connect_args={"options": "-c timezone=UTC"},
        pool_pre_ping=True,
    )


def envelope_digest(envelope: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical rendering of a submitted envelope.

    Canonical = sorted keys, no insignificant whitespace, UTF-8. The hash is what
    makes "the same claim version" checkable, so a recheck can prove the envelope
    actually changed and a resubmission can be recognised as a duplicate.
    """
    canonical = json.dumps(
        dict(envelope), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def new_run_id() -> str:
    """A fresh opaque run id (never derived from the claim id)."""
    return f"{RUN_ID_PREFIX}{uuid.uuid4().hex}"


def new_trace_id() -> str:
    """A fresh 32-hex correlation id, shared by a run and its audit events."""
    return uuid.uuid4().hex


def _lock_claim_writes(connection: Connection, tenant_id: str, claim_id: str) -> None:
    """Serialize version and decision writes for one claim for this transaction.

    A row lock cannot protect the first version because no claim row exists yet.
    The transaction-scoped advisory lock covers that case and is released by
    PostgreSQL automatically on commit or rollback.
    """
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:claim_key, 0))"),
        {"claim_key": f"{CLAIM_WRITE_LOCK_NAMESPACE}{tenant_id}:{claim_id}"},
    )


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


def _record_from_row(row: Any) -> ResultRecord:
    """Rebuild one frozen 15-key record from its stored columns."""
    values = {name: row._mapping[name] for name in _RESULT_COLUMNS}
    return ResultRecord.model_validate(values)


def _explanation_from_row(row: Any) -> ExplanationProvenance:
    """Rebuild one provenance row from the sidecar's columns."""
    values = {name: row._mapping[name] for name in _EXPLANATION_COLUMNS}
    return ExplanationProvenance.model_validate(values)


def _order_records(records: Sequence[ResultRecord]) -> list[tuple[int, ResultRecord]]:
    """Number the records 1..15 and refuse anything that is not the full set."""
    expected = set(RULE_IDS)
    produced = [record.rule_id for record in records]
    if len(produced) != len(expected) or set(produced) != expected:
        raise ReviewStoreError(
            f"a run must persist exactly the 15 documented rules; got {sorted(produced)}"
        )
    return [(index, record) for index, record in enumerate(records, start=1)]


def _order_explanations(
    explanations: Sequence[ExplanationProvenance],
    numbered: Sequence[tuple[int, ResultRecord]],
) -> list[tuple[int, ExplanationProvenance]]:
    """Pair each provenance entry with its record's position, or refuse the run.

    The sidecar must say exactly one thing about each of the run's records: a run
    stored with provenance for the wrong rule set would leave "was this text
    model-assisted?" unanswerable for the records it missed, which is the whole
    reason the sidecar exists. The ``seq`` written is the record's own position,
    so ``run_explanations.seq`` always lines up with ``rule_results.seq``.
    """
    by_rule = {entry.rule_id: entry for entry in explanations}
    expected = {record.rule_id for _, record in numbered}
    if len(by_rule) != len(explanations) or set(by_rule) != expected:
        raise ReviewStoreError(
            "explanation provenance must cover exactly the run's rules; got "
            f"{sorted(by_rule)}, expected {sorted(expected)}"
        )
    return [(seq, by_rule[record.rule_id]) for seq, record in numbered]


@dataclass(frozen=True)
class RecordedRun:
    """One persisted run plus the audit stamp and dedupe outcome."""

    run: RuleRun
    results: list[ResultRecord]
    audit: AuditStamp
    duplicate: bool = False

    @property
    def needs_attention(self) -> int:
        """How many of the run's records need a reviewer (queue membership)."""
        return sum(1 for record in self.results if requires_attention(record))


@dataclass(frozen=True)
class RecordedDecision:
    """One appended decision plus the finding's new review state and audit stamp."""

    decision: StoredDecision
    review: ReviewState
    audit: AuditStamp


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class ReviewStore:
    """All review-workflow persistence, over an injected engine."""

    def __init__(self, engine: Engine, tenant_id: str = "clinic-legacy-demo") -> None:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be blank")
        self._engine = engine
        self._tenant_id = tenant_id

    def for_tenant(self, tenant_id: str) -> ReviewStore:
        """Create a clinic-bound view over the same engine."""
        return ReviewStore(self._engine, tenant_id)

    @property
    def engine(self) -> Engine:
        """The shared database engine used by clinic directory services."""
        return self._engine

    # -- readiness ------------------------------------------------------

    def schema_revision(self) -> str | None:
        """Which migration revision the DB has applied (None when unreadable)."""
        with self._engine.connect() as connection:
            if not _table_present(connection, "rule_runs"):
                return None
            row = connection.execute(text("SELECT max(version_num) FROM alembic_version")).scalar()
            return str(row) if row is not None else None

    def ensure_schema(self) -> None:
        """Raise :class:`SchemaNotMigratedError` unless every table this module reads exists.

        Checked by table, not by revision string: a database left at an earlier
        migration must fail with the command that fixes it, naming what is
        missing, rather than 500 on the first query against a table that is not
        there yet.
        """
        with self._engine.connect() as connection:
            missing = [name for name in REQUIRED_TABLES if not _table_present(connection, name)]
        if missing:
            raise SchemaNotMigratedError(
                "the review tables are missing: run `uv run alembic upgrade head` "
                f"(migration {SCHEMA_REVISION}) against the configured database; "
                f"absent: {', '.join(missing)}"
            )

    # -- runs -----------------------------------------------------------

    def get_run(self, run_id: str) -> RuleRun | None:
        """One run, or None."""
        with self._engine.connect() as connection:
            return self._get_run(connection, run_id)

    def latest_run(self, claim_id: str) -> RuleRun | None:
        """The claim's current (highest) version, or None when never submitted."""
        with self._engine.connect() as connection:
            return self._latest_run(connection, claim_id)

    def list_runs(self, claim_id: str) -> list[RuleRun]:
        """Every version of a claim, oldest first — the retained history."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                _SELECT_RUNS.where(
                    RUNS.c.tenant_id == self._tenant_id, RUNS.c.claim_id == claim_id
                ).order_by(RUNS.c.version)
            ).all()
            return [_run_from_row(row) for row in rows]

    def get_results(self, run_id: str) -> list[ResultRecord]:
        """The run's 15 records in R001..R015 order."""
        with self._engine.connect() as connection:
            return self._get_results(connection, run_id)

    def get_claim_envelope(self, run_id: str) -> dict[str, Any] | None:
        """Return a detached copy of the immutable input envelope for one run."""
        with self._engine.connect() as connection:
            envelope = connection.execute(
                select(RUNS.c.envelope).where(
                    RUNS.c.tenant_id == self._tenant_id, RUNS.c.run_id == run_id
                )
            ).scalar_one_or_none()
            return dict(envelope) if envelope is not None else None

    def get_explanations(self, run_id: str) -> list[ExplanationProvenance]:
        """How each of the run's explanations was produced, in R001..R015 order.

        Empty for a run persisted without provenance (a direct store call): the
        reviewer surface always records it, and an absent sidecar is reported as
        absent rather than invented.
        """
        with self._engine.connect() as connection:
            return self._get_explanations(connection, run_id)

    def get_decisions(self, run_id: str) -> list[StoredDecision]:
        """Every decision recorded against a run, oldest first."""
        with self._engine.connect() as connection:
            if self._get_run(connection, run_id) is None:
                return []
            return _stored_decisions(_decision_rows(connection, [run_id]))

    def decision_history(self, run_id: str) -> DecisionHistory:
        """Every decision of a run with the review state each one produced."""
        with self._engine.connect() as connection:
            if self._get_run(connection, run_id) is None:
                return DecisionHistory(run_id=run_id, entries=[])
            rows = _decision_rows(connection, [run_id])
            counters: dict[str, int] = {}
            entries: list[DecisionHistoryEntry] = []
            for row in rows:
                rule_id = str(row.rule_id)
                counters[rule_id] = counters.get(rule_id, 0) + 1
                entries.append(
                    DecisionHistoryEntry(
                        decision=_stored_decision(row),
                        review=ReviewState(
                            status=ACTION_STATUS[row.action],
                            action=row.action,
                            actor=str(row.actor),
                            reason=str(row.reason),
                            decided_at=row.created_at,
                            decision_count=counters[rule_id],
                        ),
                    )
                )
            return DecisionHistory(run_id=run_id, entries=entries)

    def run_audit_stamp(self, run_id: str) -> AuditStamp:
        """The audit stamp of a run's own ledger event, or raise :class:`RunNotFoundError`."""
        with self._engine.connect() as connection:
            if self._get_run(connection, run_id) is None:
                raise RunNotFoundError(f"unknown run: {run_id}")
            return self._run_stamp(connection, run_id)

    def record_run(
        self,
        envelope: Mapping[str, Any],
        records: Sequence[ResultRecord],
        *,
        rule_version: str,
        model_version: str,
        prompt_version: str,
        initiated_by: str,
        explanations: Sequence[ExplanationProvenance] | None = None,
    ) -> RecordedRun:
        """Persist a first (or resubmitted) version of a claim and its audit event.

        A submission whose canonical bytes equal the claim's current version is
        **not** a new version: it returns that run with ``duplicate=True`` and
        writes nothing. Otherwise the new version is ``latest + 1``.

        ``explanations`` is the per-record provenance of the reviewer-facing
        explanations, one entry per record in R001..R015 order. Omitted, the run
        is stored without provenance (the records are then stored exactly as
        handed in); the reviewer surface always supplies it.
        """
        with self._engine.begin() as connection:
            claim_id = envelope.get("claim_id")
            if not isinstance(claim_id, str) or not claim_id:
                raise ReviewStoreError("the envelope has no claim_id")
            _lock_claim_writes(connection, self._tenant_id, claim_id)
            digest = envelope_digest(envelope)
            latest = self._latest_run(connection, claim_id)
            if latest is not None and latest.input_hash == digest:
                return RecordedRun(
                    run=latest,
                    results=self._get_results(connection, latest.run_id),
                    audit=self._run_stamp(connection, latest.run_id),
                    duplicate=True,
                )
            version = 1 if latest is None else latest.version + 1
            return self._persist_run(
                connection,
                envelope=envelope,
                records=records,
                explanations=explanations,
                digest=digest,
                version=version,
                supersedes_run_id=None if latest is None else latest.run_id,
                rule_version=rule_version,
                model_version=model_version,
                prompt_version=prompt_version,
                initiated_by=initiated_by,
            )

    def record_recheck(
        self,
        envelope: Mapping[str, Any],
        records: Sequence[ResultRecord],
        *,
        rule_version: str,
        model_version: str,
        prompt_version: str,
        initiated_by: str,
        explanations: Sequence[ExplanationProvenance] | None = None,
    ) -> RecordedRun:
        """Persist a corrected envelope as a NEW version that supersedes the old one.

        Refuses when the claim was never submitted, and refuses an envelope whose
        canonical bytes are unchanged (:class:`NoCorrectionError`): a
        "correction" that changes nothing would create a version that differs
        from its predecessor only in a timestamp, which is exactly the kind of
        unverifiable claim this workflow exists to prevent.
        """
        with self._engine.begin() as connection:
            claim_id = envelope.get("claim_id")
            if not isinstance(claim_id, str) or not claim_id:
                raise ReviewStoreError("the envelope has no claim_id")
            _lock_claim_writes(connection, self._tenant_id, claim_id)
            latest = self._latest_run(connection, claim_id)
            if latest is None:
                raise RunNotFoundError(f"claim {claim_id!r} has no run to recheck")
            digest = envelope_digest(envelope)
            if digest == latest.input_hash:
                raise NoCorrectionError(
                    f"the submitted envelope is identical to run {latest.run_id}; "
                    "a recheck must carry a real correction"
                )
            return self._persist_run(
                connection,
                envelope=envelope,
                records=records,
                explanations=explanations,
                digest=digest,
                version=latest.version + 1,
                supersedes_run_id=latest.run_id,
                rule_version=rule_version,
                model_version=model_version,
                prompt_version=prompt_version,
                initiated_by=initiated_by,
            )

    def _persist_run(
        self,
        connection: Connection,
        *,
        envelope: Mapping[str, Any],
        records: Sequence[ResultRecord],
        digest: str,
        version: int,
        supersedes_run_id: str | None,
        rule_version: str,
        model_version: str,
        prompt_version: str,
        initiated_by: str,
        explanations: Sequence[ExplanationProvenance] | None = None,
    ) -> RecordedRun:
        """Write the run row, its 15 records, its provenance and its audit event atomically."""
        numbered = _order_records(records)
        run_id = new_run_id()
        trace_id = new_trace_id()
        run_row = connection.execute(
            insert(RUNS)
            .values(
                run_id=run_id,
                tenant_id=self._tenant_id,
                claim_id=envelope["claim_id"],
                version=version,
                supersedes_run_id=supersedes_run_id,
                input_hash=digest,
                envelope=dict(envelope),
                trace_id=trace_id,
                rule_version=rule_version,
                model_version=model_version,
                prompt_version=prompt_version,
                initiated_by=initiated_by,
                created_at=func.now(),
            )
            .returning(*_RUN_COLUMNS)
        ).one()
        connection.execute(
            insert(RESULTS),
            [
                {
                    "run_id": run_id,
                    "tenant_id": self._tenant_id,
                    "claim_id": record.claim_id,
                    "seq": seq,
                    "rule_id": record.rule_id,
                    "rule_version": record.rule_version,
                    "status": record.status.value,
                    "severity": record.severity.value,
                    "affected_line_ids": list(record.affected_line_ids),
                    "evidence": [entry.model_dump() for entry in record.evidence],
                    "rule_source": record.rule_source,
                    "explanation": record.explanation,
                    "corrective_action": record.corrective_action,
                    "confidence": record.confidence,
                    "confidence_kind": record.confidence_kind.value,
                    "requires_human_review": record.requires_human_review,
                    "method": record.method,
                    "review_status": record.review_status,
                    "created_at": func.now(),
                }
                for seq, record in numbered
            ],
        )
        stamp = audit_events.append(
            connection,
            audit_events.run_event(
                run_id=run_id,
                trace_id=trace_id,
                input_hash=digest,
                rule_version=rule_version,
                model_version=model_version,
                prompt_version=prompt_version,
                actor=initiated_by,
                finding_ids=[
                    record.rule_id for _, record in numbered if requires_attention(record)
                ],
            ),
        )
        if explanations is not None:
            connection.execute(
                insert(EXPLANATIONS),
                [
                    {
                        "run_id": run_id,
                        "tenant_id": self._tenant_id,
                        "rule_id": provenance.rule_id,
                        "seq": seq,
                        "source": provenance.source,
                        "provider": provenance.provider,
                        "rewritten": provenance.rewritten,
                        "fallback_used": provenance.fallback_used,
                        "correction_recommendation": provenance.correction_recommendation,
                        "cited_evidence_paths": list(provenance.cited_evidence_paths),
                        "security_decision": provenance.security_decision,
                        "receipt_sha256": provenance.receipt_sha256,
                        "rejection_reasons": list(provenance.rejection_reasons),
                        "declined_reason": provenance.declined_reason,
                    }
                    for seq, provenance in _order_explanations(explanations, numbered)
                ],
            )
        return RecordedRun(
            run=_run_from_row(run_row),
            results=[record for _, record in numbered],
            audit=stamp,
        )

    def _get_run(self, connection: Connection, run_id: str) -> RuleRun | None:
        row = connection.execute(
            _SELECT_RUNS.where(RUNS.c.tenant_id == self._tenant_id, RUNS.c.run_id == run_id)
        ).one_or_none()
        return None if row is None else _run_from_row(row)

    def _latest_run(self, connection: Connection, claim_id: str) -> RuleRun | None:
        row = connection.execute(
            _SELECT_RUNS.where(RUNS.c.tenant_id == self._tenant_id, RUNS.c.claim_id == claim_id)
            .order_by(RUNS.c.version.desc())
            .limit(1)
        ).one_or_none()
        return None if row is None else _run_from_row(row)

    def _get_results(self, connection: Connection, run_id: str) -> list[ResultRecord]:
        rows = connection.execute(
            select(*[RESULTS.c[name] for name in _RESULT_COLUMNS])
            .where(RESULTS.c.tenant_id == self._tenant_id, RESULTS.c.run_id == run_id)
            .order_by(RESULTS.c.seq)
        ).all()
        return [_record_from_row(row) for row in rows]

    def _get_record(self, connection: Connection, run_id: str, rule_id: str) -> ResultRecord | None:
        row = connection.execute(
            select(*[RESULTS.c[name] for name in _RESULT_COLUMNS])
            .where(
                and_(
                    RESULTS.c.tenant_id == self._tenant_id,
                    RESULTS.c.run_id == run_id,
                    RESULTS.c.rule_id == rule_id,
                )
            )
            .limit(1)
        ).one_or_none()
        return None if row is None else _record_from_row(row)

    def _get_explanations(self, connection: Connection, run_id: str) -> list[ExplanationProvenance]:
        rows = connection.execute(
            select(*[EXPLANATIONS.c[name] for name in _EXPLANATION_COLUMNS])
            .where(EXPLANATIONS.c.tenant_id == self._tenant_id, EXPLANATIONS.c.run_id == run_id)
            .order_by(EXPLANATIONS.c.seq)
        ).all()
        return [_explanation_from_row(row) for row in rows]

    def _run_stamp(self, connection: Connection, run_id: str) -> AuditStamp:
        """The audit stamp of a run's own event (the first event for that reference)."""
        for event in audit_events.events_for_ref(connection, run_id):
            if event.kind == audit_events.RUN_KIND:
                return AuditStamp(
                    event_id=event.event_id,
                    at=event.at,
                    kind=event.kind,
                    chain_hash=event.chain_hash,
                )
        raise ReviewStoreError(f"run {run_id} has no audit event")  # pragma: no cover

    # -- decisions ------------------------------------------------------

    def record_decision(self, run_id: str, request: DecisionRequest) -> RecordedDecision:
        """Append one reviewer decision, its audit event, and report the new state.

        Ordered checks, so the reviewer gets the most useful reason first:

        1.  the run exists, and its finding exists (404 otherwise);
        2.  the run is still the claim's current version (409 otherwise — the
            claim was corrected, so the answer belongs to the new version's
            finding, and the old records stay as they were);
        3.  the decision state machine allows the action (409 otherwise);
        4.  the pack's 7-key event contract accepts the event. The event is built
            from the stored finding and the database clock, then validated: a
            model violation rolls the transaction back, so a decision row and its
            audit event are all-or-nothing.
        """
        with self._engine.begin() as connection:
            run = self._get_run(connection, run_id)
            if run is None:
                raise RunNotFoundError(f"unknown run: {run_id}")
            _lock_claim_writes(connection, self._tenant_id, run.claim_id)
            record = self._get_record(connection, run_id, request.rule_id)
            if record is None:
                raise FindingNotFoundError(f"run {run_id} has no result for {request.rule_id}")
            latest = self._latest_run(connection, run.claim_id)
            if latest is None or latest.run_id != run_id:  # pragma: no cover - defensive
                raise RunSupersededError(
                    f"run {run_id} was superseded by "
                    f"{'a newer version' if latest else 'no run'}; decide on the current version"
                )
            state = _reviews_for(connection, [run_id]).get((run_id, request.rule_id), ReviewState())
            new_status = next_status(state.status, request.action)
            row = connection.execute(
                insert(DECISIONS)
                .values(
                    decision_id=uuid.uuid4(),
                    tenant_id=self._tenant_id,
                    run_id=run_id,
                    claim_id=run.claim_id,
                    rule_id=request.rule_id,
                    action=request.action.value,
                    actor=request.actor,
                    reason=request.reason,
                    original_status=record.status.value,
                    created_at=func.now(),
                )
                .returning(DECISIONS.c.decision_id, DECISIONS.c.created_at)
            ).one()
            event = ReviewDecisionEvent(
                claim_id=run.claim_id,
                rule_id=request.rule_id,
                action=request.action,
                actor=request.actor,
                reason=request.reason,
                created_at=row.created_at,
                original_status=record.status,
            )
            stamp = audit_events.append(
                connection,
                audit_events.decision_event(
                    run_id=run_id,
                    trace_id=run.trace_id,
                    rule_id=request.rule_id,
                    action=request.action.value,
                    rule_version=run.rule_version,
                    model_version=run.model_version,
                ),
            )
        return RecordedDecision(
            decision=StoredDecision(decision_id=str(row.decision_id), run_id=run_id, event=event),
            review=ReviewState(
                status=new_status,
                action=request.action,
                actor=request.actor,
                reason=request.reason,
                decided_at=row.created_at,
                decision_count=state.decision_count + 1,
            ),
            audit=stamp,
        )

    # -- queue ----------------------------------------------------------

    def queue(self, filters: QueueFilters | None = None) -> ReviewQueue:
        """The current review queue: latest version per claim, filtered, with counts.

        Counts describe the returned set, so "N unresolved" always refers to what
        the reviewer is looking at. By default only checks that need attention are
        listed (a failed, abstaining or unimplemented check); ``include_all``
        lists the full 15 per claim so a reviewer can also dismiss a passing check.
        """
        return self.queue_for_claim_ids(None, filters)

    def queue_for_claim_ids(
        self, claim_ids: Sequence[str] | None, filters: QueueFilters | None = None
    ) -> ReviewQueue:
        """Return only the supplied clinic claims; None means the team queue."""
        applied = filters if filters is not None else QueueFilters()
        with self._engine.connect() as connection:
            rows = connection.execute(_queue_statement(applied, self._tenant_id, claim_ids)).all()
            run_ids = list(dict.fromkeys(str(row.run_id) for row in rows))
            reviews = _reviews_for(connection, run_ids)
            items = [
                FindingView(
                    run_id=str(row.run_id),
                    claim_id=str(row.claim_id),
                    version=int(row.version),
                    run_created_at=row.run_created_at,
                    record=_record_from_row(row),
                    review=reviews.get((str(row.run_id), str(row.rule_id)), ReviewState()),
                )
                for row in rows
            ]
        return ReviewQueue(
            filters=applied,
            counts=_queue_counts(items),
            claims=_claim_summaries(items),
            items=items,
        )


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------

#: Columns read/returned for a run row (one definition, so the mapping and the
#: ``RETURNING`` clause cannot drift).
_RUN_COLUMNS: tuple[Any, ...] = (
    RUNS.c.run_id,
    RUNS.c.claim_id,
    RUNS.c.version,
    RUNS.c.supersedes_run_id,
    RUNS.c.input_hash,
    RUNS.c.trace_id,
    RUNS.c.rule_version,
    RUNS.c.model_version,
    RUNS.c.prompt_version,
    RUNS.c.initiated_by,
    RUNS.c.created_at,
)

#: Columns read/returned for a decision row.
_DECISION_COLUMNS: tuple[Any, ...] = (
    DECISIONS.c.decision_id,
    DECISIONS.c.run_id,
    DECISIONS.c.claim_id,
    DECISIONS.c.rule_id,
    DECISIONS.c.action,
    DECISIONS.c.actor,
    DECISIONS.c.reason,
    DECISIONS.c.original_status,
    DECISIONS.c.created_at,
)

_SELECT_RUNS: Select[Any] = select(*_RUN_COLUMNS)


def _run_from_row(row: Any) -> RuleRun:
    return RuleRun(
        run_id=str(row.run_id),
        claim_id=str(row.claim_id),
        version=int(row.version),
        input_hash=str(row.input_hash),
        trace_id=str(row.trace_id),
        rule_version=str(row.rule_version),
        model_version=str(row.model_version),
        prompt_version=str(row.prompt_version),
        initiated_by=str(row.initiated_by),
        created_at=row.created_at,
        supersedes_run_id=None if row.supersedes_run_id is None else str(row.supersedes_run_id),
    )


def _stored_decision(row: Any) -> StoredDecision:
    return StoredDecision(
        decision_id=str(row.decision_id),
        run_id=str(row.run_id),
        event=ReviewDecisionEvent(
            claim_id=str(row.claim_id),
            rule_id=str(row.rule_id),
            action=row.action,
            actor=str(row.actor),
            reason=str(row.reason),
            created_at=row.created_at,
            original_status=Status(row.original_status),
        ),
    )


def _stored_decisions(rows: Sequence[Any]) -> list[StoredDecision]:
    return [_stored_decision(row) for row in rows]


def _decision_rows(connection: Connection, run_ids: Sequence[str]) -> list[Any]:
    if not run_ids:
        return []
    # (created_at, seq): created_at is the transaction clock, seq breaks ties
    # deterministically, so readers agree on the current state.
    return list(
        connection.execute(
            select(*_DECISION_COLUMNS)
            .where(DECISIONS.c.run_id.in_(list(run_ids)))
            .order_by(DECISIONS.c.created_at, DECISIONS.c.seq)
        ).all()
    )


def _reviews_for(
    connection: Connection, run_ids: Sequence[str]
) -> dict[tuple[str, str], ReviewState]:
    """The current review state per ``(run_id, rule_id)``, from the decisions."""
    grouped: dict[tuple[str, str], list[Any]] = {}
    for row in _decision_rows(connection, run_ids):
        grouped.setdefault((str(row.run_id), str(row.rule_id)), []).append(row)
    states: dict[tuple[str, str], ReviewState] = {}
    for key, rows in grouped.items():
        last = rows[-1]
        states[key] = ReviewState(
            status=ACTION_STATUS[last.action],
            action=last.action,
            actor=str(last.actor),
            reason=str(last.reason),
            decided_at=last.created_at,
            decision_count=len(rows),
        )
    return states


def _queue_statement(
    filters: QueueFilters, tenant_id: str, claim_ids: Sequence[str] | None = None
) -> Select[Any]:
    """Select the latest version's records, filtered, in claim/rule order."""
    ranked = (
        select(
            RUNS.c.run_id,
            RUNS.c.tenant_id,
            RUNS.c.claim_id,
            RUNS.c.version,
            RUNS.c.created_at,
            func.row_number()
            .over(partition_by=(RUNS.c.tenant_id, RUNS.c.claim_id), order_by=RUNS.c.version.desc())
            .label("rank"),
        )
        .where(RUNS.c.tenant_id == tenant_id)
        .subquery("ranked_runs")
    )
    conditions: list[ColumnElement[bool]] = []
    if filters.claim_id:
        conditions.append(RESULTS.c.claim_id == filters.claim_id)
    if claim_ids is not None:
        conditions.append(RESULTS.c.claim_id.in_(list(claim_ids)))
    if filters.rule_id:
        conditions.append(RESULTS.c.rule_id == filters.rule_id)
    if filters.status is not None:
        conditions.append(RESULTS.c.status == filters.status.value)
    if filters.severity is not None:
        conditions.append(RESULTS.c.severity == filters.severity.value)
    if not filters.include_all:
        conditions.append(
            or_(
                RESULTS.c.requires_human_review.is_(True),
                RESULTS.c.status == Status.NOT_IMPLEMENTED.value,
            )
        )
    return (
        select(
            RESULTS.c.run_id,
            ranked.c.version,
            ranked.c.created_at.label("run_created_at"),
            *[RESULTS.c[name] for name in _RESULT_COLUMNS],
        )
        .select_from(
            RESULTS.join(
                ranked,
                and_(ranked.c.run_id == RESULTS.c.run_id, RESULTS.c.tenant_id == tenant_id),
            )
        )
        .where(ranked.c.rank == 1)
        .where(*conditions)
        .order_by(RESULTS.c.claim_id, RESULTS.c.seq)
    )


def _queue_counts(items: Sequence[FindingView]) -> QueueCounts:
    by_review: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for item in items:
        by_review[item.review.status.value] = by_review.get(item.review.status.value, 0) + 1
        by_severity[item.record.severity.value] = by_severity.get(item.record.severity.value, 0) + 1
    unresolved = sum(1 for item in items if item.needs_attention and item.review.unresolved)
    return QueueCounts(
        findings=len(items),
        unresolved=unresolved,
        resolved=sum(1 for item in items if item.needs_attention and not item.review.unresolved),
        by_rule_status=summarize_statuses([item.record for item in items]),
        by_review_status=by_review,
        by_severity=by_severity,
    )


def _claim_summaries(items: Sequence[FindingView]) -> list[ClaimQueueSummary]:
    summaries: dict[str, ClaimQueueSummary] = {}
    for item in items:
        previous = summaries.get(item.claim_id)
        decided = item.review.decided_at
        latest = previous.latest_decision_at if previous is not None else None
        if decided is not None and (latest is None or decided > latest):
            latest = decided
        summaries[item.claim_id] = ClaimQueueSummary(
            claim_id=item.claim_id,
            run_id=item.run_id,
            version=item.version if previous is None else max(previous.version, item.version),
            findings=(0 if previous is None else previous.findings) + 1,
            unresolved=(0 if previous is None else previous.unresolved)
            + (1 if item.needs_attention and item.review.unresolved else 0),
            latest_decision_at=latest,
        )
    return [summaries[key] for key in sorted(summaries)]
