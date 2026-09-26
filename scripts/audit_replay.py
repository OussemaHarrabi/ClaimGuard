"""Audit replay: reconstruct one stored run from the append-only ledger (gap G3).

The Phase-1 scoring asks for "An audit log engine: append-only, tamper-evident,
**replayable** history". The chain was already verifiable; what was missing was a
demonstration that a *past decision can be reconstructed*. This script produces
that demonstration for one ``run_id`` and prints a transcript.

What one replay does, in order::

    uv run python scripts/audit_replay.py --run-id RUN-<32 hex>

1.  **Read the stored facts back** — the run row, the immutable input envelope
    (the ``GET /v1/runs/{id}/claim`` semantics, read through the store rather
    than over HTTP), the 15 stored records, and each record's explanation
    provenance.
2.  **Re-run the deterministic engine over the stored envelope** and reproduce
    the reviewer-facing records exactly as ``POST /v1/claims`` does with no model
    configured (``evaluate_claim`` then the bounded explanation layer with its
    deterministic template provider), then compare the replay against the stored
    records field by field.
3.  **Walk the ledger rows for that run** and verify them: each row's
    ``chain_hash`` must recompute from its own fields (the Python replica of the
    trigger's serialisation), each row's ``prev_hash`` must be its predecessor's
    ``chain_hash`` in ``(at, event_id)`` order, and the run event's versions,
    input hash and actor must agree with the run it claims to describe.
4.  **Print the transcript** — input hash, catalogue identity, rule/model/prompt
    versions, per-rule agreement, every ledger row with its hashes, and the
    verdict.

The comparison is deliberately not a copy of the results table: the replay never
reads a stored ``status``, ``severity`` or ``evidence`` list as an input. Those
fields are recomputed from the envelope and only then compared.

``explanation`` is the one field the deterministic engine does not own: it is
produced by the bounded explanation layer, which may hand the wording to a model
(``docs/19``). A record whose provenance says the text was drafted by a model is
reported as ``model-drafted`` — not replayed, by design, and not counted as a
disagreement. Every other field of every record must agree exactly.

Exit codes: ``0`` the replay reproduced the stored run and the ledger verifies;
``1`` it did not (a disagreement, or a broken chain — a defect either way);
``2`` refused (bad usage, unreachable database, unresolvable catalogue, unknown
run). Nothing here writes: the replay is read-only over the database.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claimguard.audit.chain import GENESIS
from claimguard.edu.emit import validate_record
from claimguard.edu.engine import evaluate_claim
from claimguard.edu.envelope import RESULT_KEYS
from claimguard.edu.explain import TemplateExplanationProvider
from claimguard.edu.policy import (
    DIAGNOSIS_FILE,
    POLICY_FILE,
    PROVIDER_FILE,
    RULE_FILE,
    SERVICE_FILE,
    RuleContext,
    RuleDirError,
)
from claimguard.review import audit_events
from claimguard.review.app import resolve_rules_dir
from claimguard.review.explanations import explain_run
from claimguard.review.models import ExplanationProvenance, RuleRun, requires_attention
from claimguard.review.store import ReviewStore, build_engine, envelope_digest, resolve_dsn
from sqlalchemy import Engine, select, tuple_
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

#: The fields compared exactly between a stored record and its replay. Every
#: 15-key field except ``explanation``: that text is produced by the bounded
#: explanation layer, which may hand the wording to a model, so it is judged
#: through its recorded provenance (see :func:`compare_record`).
ENGINE_FIELDS: Final[tuple[str, ...]] = tuple(key for key in RESULT_KEYS if key != "explanation")

#: ``explanation`` comparison outcomes.
EXPLANATION_REPRODUCED: Final = "reproduced"
EXPLANATION_MODEL_DRAFTED: Final = "model-drafted"
EXPLANATION_DIFFERS: Final = "differs"

#: Reported in ``differing_fields`` when the run does not hold a record at all.
MISSING_RECORD: Final = "record-missing"

#: The catalogue files whose digests identify the rule catalogue of a replay.
CATALOGUE_FILES: Final[tuple[str, ...]] = (
    POLICY_FILE,
    SERVICE_FILE,
    PROVIDER_FILE,
    DIAGNOSIS_FILE,
    RULE_FILE,
)

EXIT_OK: Final = 0
EXIT_MISMATCH: Final = 1
EXIT_REFUSED: Final = 2


class ReplayError(RuntimeError):
    """The replay cannot be produced (usage, database, catalogue or unknown run)."""


def _emit(text: str) -> None:
    """Write one line to stdout (ruff's T20 forbids ``print`` in this tree)."""
    sys.stdout.write(text + "\n")


def _redact_dsn(dsn: str) -> str:
    """Hide the password in a DSN before it reaches a transcript."""
    scheme, separator, rest = dsn.partition("://")
    if not separator:
        return dsn
    credentials, at, host = rest.partition("@")
    if not at:
        return dsn
    user, colon, _password = credentials.partition(":")
    return f"{scheme}://{user}{':' if colon else ''}***@{host}"


# ---------------------------------------------------------------------------
# Catalogue identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogueIdentity:
    """Which rule catalogue the replay ran with (the run's rule version alone is not enough)."""

    rules_dir: str
    digest: str
    files: int
    rules: int


def catalogue_identity(rules_dir: Path, context: RuleContext) -> CatalogueIdentity:
    """Digest the catalogue files the replay loaded, so a drifted catalogue is visible.

    One digest over the file names and their contents (not a directory mtime):
    two replays of the same run print the same value, and a replay proves which
    catalogue it used instead of asserting that it is the right one.
    """
    digest = hashlib.sha256()
    files = 0
    for name in CATALOGUE_FILES:
        path = rules_dir / name
        if not path.is_file():
            continue
        files += 1
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return CatalogueIdentity(
        rules_dir=str(rules_dir), digest=digest.hexdigest(), files=files, rules=len(context.rules)
    )


# ---------------------------------------------------------------------------
# Comparison (pure): one stored record against its replay
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordComparison:
    """How one rule's stored record compares with the record the replay produced."""

    rule_id: str
    stored_status: str
    differing_fields: tuple[str, ...]
    explanation: str

    @property
    def agrees(self) -> bool:
        """True when no field differs and the explanation is accounted for."""
        return not self.differing_fields and self.explanation != EXPLANATION_DIFFERS


def compare_record(
    stored: Mapping[str, Any] | None,
    reproduced: Mapping[str, Any] | None,
    provenance: ExplanationProvenance | None,
) -> RecordComparison:
    """Compare one stored 15-key record against its replay, field by field.

    ``stored`` and ``reproduced`` are the JSON forms of validated result records,
    or ``None`` when that rule is absent on one side (a coverage defect, reported
    rather than skipped). ``provenance`` is the stored explanation provenance for
    that rule — the only authority on whether the reviewer-facing text was
    allowed to come from a model.

    ``explanation`` outcomes: ``reproduced`` (the deterministic text matches),
    ``model-drafted`` (the stored text came from a model — not replayed, by
    design, because a model is not deterministic), or ``differs`` (a defect).
    """
    known = stored if stored is not None else reproduced
    fallback_rule_id = provenance.rule_id if provenance is not None else "?"
    rule_id = str(known.get("rule_id") if known is not None else fallback_rule_id)
    stored_status = str(stored["status"]) if stored is not None else "?"
    if stored is None or reproduced is None:
        return RecordComparison(
            rule_id=rule_id,
            stored_status=stored_status,
            differing_fields=(MISSING_RECORD,),
            explanation=EXPLANATION_DIFFERS,
        )
    differing = tuple(key for key in ENGINE_FIELDS if stored.get(key) != reproduced.get(key))
    if stored.get("explanation") == reproduced.get("explanation"):
        explanation = EXPLANATION_REPRODUCED
    elif provenance is not None and provenance.model_assisted:
        explanation = EXPLANATION_MODEL_DRAFTED
    else:
        explanation = EXPLANATION_DIFFERS
    return RecordComparison(
        rule_id=rule_id,
        stored_status=stored_status,
        differing_fields=differing,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Ledger walk
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainLink:
    """One ledger row of the run, plus its position in the run's own event list."""

    index: int
    event_id: str
    at: str
    kind: str
    trace_id: str
    decision: str | None
    reason_code: str | None
    finding_ids: tuple[str, ...]
    rule_version: str | None
    model_version: str | None
    prev_hash: str
    chain_hash: str


@dataclass(frozen=True)
class ChainReport:
    """The result of walking the run's ledger rows and their links."""

    events: tuple[ChainLink, ...]
    content_broken: tuple[str, ...]
    link_broken_index: int | None
    anchor_hash: str
    anchor_event_id: str | None
    run_event_mismatches: tuple[str, ...]
    run_event_provenance: Mapping[str, str]

    @property
    def ok(self) -> bool:
        """True when every row is intact, linked end to end, and describes this run."""
        return (
            not self.content_broken
            and self.link_broken_index is None
            and not self.run_event_mismatches
        )


def first_broken_link(events: Sequence[ChainLink], expected_prev: Sequence[str]) -> int | None:
    """Index of the first event whose ``prev_hash`` is not its ledger predecessor's hash.

    ``expected_prev`` holds, for each event, the ``chain_hash`` of the row that
    immediately precedes it **in the whole ledger** (``genesis`` when it is the
    first row). The ledger is one global chain: other runs append between this
    run's own events, so a run's second event legitimately chains to some *other*
    run's event rather than to its own first one. Comparing a run's events against
    each other would report a false break on any run whose decision arrived after
    unrelated activity — which is the normal case in a shared ledger.

    Pure, so the rule is testable without a database: a row cut from the middle
    breaks the link of the row that followed it, while cutting the tail does not.
    """
    for position, event in enumerate(events):
        if event.prev_hash != expected_prev[position]:
            return position
    return None


def contiguous_expected_prev(events: Sequence[ChainLink], anchor_hash: str) -> tuple[str, ...]:
    """The expected predecessors when the events *are* adjacent in the ledger.

    Only correct for a run whose events nothing else interleaved with — the shape
    a just-created run has, and the shape the pipeline tests build. Real runs are
    checked against the ledger itself (``_ledger_predecessors``).
    """
    expected: list[str] = []
    previous = anchor_hash
    for event in events:
        expected.append(previous)
        previous = event.chain_hash
    return tuple(expected)


def run_event_mismatches(
    events: Sequence[ChainLink], run: RuleRun, attention_rule_ids: Sequence[str]
) -> tuple[str, ...]:
    """Every way the run event disagrees with the run row it claims to describe.

    This is what makes the ledger a *reconstructable* history: an auditor holding
    only the ledger can read the trace id, the input hash, the prompt version and
    the actor out of the run's ``validated`` event, and the rule and model
    versions out of its own columns — so all of them must be the run's own. The
    event's ``finding_ids`` are the checks that needed a human eye, which the
    stored records also tell us, so the two must agree as well.
    """
    run_events = [event for event in events if event.kind == audit_events.RUN_KIND]
    if not run_events:
        return ("the run has no 'validated' ledger event",)
    if len(run_events) > 1:
        return (f"the run has {len(run_events)} 'validated' ledger events, expected 1",)
    recorded = run_events[0]
    problems: list[str] = []
    if recorded.trace_id != run.trace_id:
        problems.append(f"trace_id ledger={recorded.trace_id!r} run={run.trace_id!r}")
    if recorded.rule_version != run.rule_version:
        problems.append(f"rule_version ledger={recorded.rule_version!r} run={run.rule_version!r}")
    if recorded.model_version != run.model_version:
        problems.append(
            f"model_version ledger={recorded.model_version!r} run={run.model_version!r}"
        )
    provenance = audit_events.parse_provenance(recorded.reason_code)
    for key, expected in (
        (audit_events.PROVENANCE_INPUT_KEY, run.input_hash),
        (audit_events.PROVENANCE_PROMPT_KEY, run.prompt_version),
        (audit_events.PROVENANCE_ACTOR_KEY, run.initiated_by),
    ):
        if provenance.get(key) != expected:
            problems.append(f"{key} ledger={provenance.get(key)!r} run={expected!r}")
    if recorded.finding_ids != tuple(attention_rule_ids):
        problems.append(
            f"finding_ids ledger={list(recorded.finding_ids)} "
            f"stored records needing attention={list(attention_rule_ids)}"
        )
    return tuple(problems)


def _link(position: int, row: audit_events.AuditEventRow) -> ChainLink:
    """One ledger row as a transcript-ready link of the run's own event list."""
    return ChainLink(
        index=position,
        event_id=row.event_id,
        at=row.at.isoformat(),
        kind=row.kind,
        trace_id=row.trace_id,
        decision=row.decision,
        reason_code=row.reason_code,
        finding_ids=tuple(row.finding_ids),
        rule_version=row.rule_version,
        model_version=row.model_version,
        prev_hash=row.prev_hash,
        chain_hash=row.chain_hash,
    )


def _ledger_anchor(connection: Connection, first: audit_events.AuditEventRow) -> tuple[str, str]:
    """The predecessor of the run's first event: ``(chain_hash, event_id)``.

    Read from the live ledger, not assumed: an earlier row's hash is what the
    run's first event must chain to. ``(GENESIS, "")`` when the run's first event
    is itself the first row of the ledger.
    """
    row = connection.execute(
        select(audit_events.AUDIT_EVENTS.c.chain_hash, audit_events.AUDIT_EVENTS.c.event_id)
        .where(
            tuple_(audit_events.AUDIT_EVENTS.c.at, audit_events.AUDIT_EVENTS.c.event_id)
            < (first.at, uuid.UUID(first.event_id))
        )
        .order_by(
            audit_events.AUDIT_EVENTS.c.at.desc(), audit_events.AUDIT_EVENTS.c.event_id.desc()
        )
        .limit(1)
    ).first()
    if row is None:
        return GENESIS, ""
    return str(row[0]), str(row[1])


def _ledger_predecessors(
    connection: Connection, rows: Sequence[audit_events.AuditEventRow]
) -> tuple[str, ...]:
    """For each row, the ``chain_hash`` of the ledger row immediately before it.

    Read from the live ledger in ``(at, event_id)`` order, which is the order the
    trigger and ``claimguard.verify_audit_chain()`` both use. This is the only
    correct way to check linkage on a shared ledger: rows belonging to other runs
    sit between this run's rows, and each row must chain to whatever was actually
    last written, not to a sibling event of the same run.
    """
    expected: list[str] = []
    for row in rows:
        predecessor = connection.execute(
            select(audit_events.AUDIT_EVENTS.c.chain_hash)
            .where(
                tuple_(audit_events.AUDIT_EVENTS.c.at, audit_events.AUDIT_EVENTS.c.event_id)
                < (row.at, uuid.UUID(row.event_id))
            )
            .order_by(
                audit_events.AUDIT_EVENTS.c.at.desc(), audit_events.AUDIT_EVENTS.c.event_id.desc()
            )
            .limit(1)
        ).first()
        expected.append(str(predecessor[0]) if predecessor is not None else GENESIS)
    return tuple(expected)


def walk_run_chain(
    *,
    engine: Engine,
    run: RuleRun,
    attention_rule_ids: Sequence[str],
) -> ChainReport:
    """Verify the run's ledger rows: content, links, and agreement with the run row.

    Content is checked by ``claimguard.review.audit_events.unlinked_refs`` — the
    same recomputation ``claimguard.verify_audit_chain()`` performs — and linkage
    by walking ``(at, event_id)`` order from the ledger row that precedes the
    run's first event.
    """
    with engine.connect() as connection:
        rows = audit_events.events_for_ref(connection, run.run_id)
        broken = audit_events.unlinked_refs(connection, [run.run_id]).get(run.run_id, [])
        anchor_hash, anchor_event_id = (
            _ledger_anchor(connection, rows[0]) if rows else (GENESIS, "")
        )
        expected_prev = _ledger_predecessors(connection, rows)
    events = tuple(_link(position, row) for position, row in enumerate(rows, start=1))
    run_event = next(
        (event for event in events if event.kind == audit_events.RUN_KIND),
        None,
    )
    return ChainReport(
        events=events,
        content_broken=tuple(broken),
        link_broken_index=first_broken_link(events, expected_prev),
        anchor_hash=anchor_hash,
        anchor_event_id=anchor_event_id or None,
        run_event_mismatches=run_event_mismatches(events, run, attention_rule_ids),
        run_event_provenance=(
            audit_events.parse_provenance(run_event.reason_code) if run_event else {}
        ),
    )


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayReport:
    """Everything one replay established, ready to render or assert on."""

    run: RuleRun
    database: str
    schema_revision: str | None
    catalogue: CatalogueIdentity
    envelope_keys: int
    stored_input_hash: str
    recomputed_input_hash: str
    comparisons: tuple[RecordComparison, ...]
    chain: ChainReport

    @property
    def hash_matches(self) -> bool:
        """True when the stored envelope is the one the run row hashed."""
        return self.stored_input_hash == self.recomputed_input_hash

    @property
    def agreements(self) -> int:
        """How many rules were reproduced (agreement on every engine field)."""
        return sum(1 for comparison in self.comparisons if comparison.agrees)

    @property
    def disagreements(self) -> tuple[RecordComparison, ...]:
        """The records that did not reproduce — a defect, never expected."""
        return tuple(comparison for comparison in self.comparisons if not comparison.agrees)

    @property
    def ok(self) -> bool:
        """True when the replay reproduces the stored run and the ledger verifies."""
        return self.hash_matches and not self.disagreements and self.chain.ok

    @property
    def exit_code(self) -> int:
        return EXIT_OK if self.ok else EXIT_MISMATCH


def replay_run(*, store: ReviewStore, engine: Engine, run_id: str, rules_dir: Path) -> ReplayReport:
    """Reconstruct one stored run from its stored envelope and verify its ledger rows.

    Read-only: nothing here writes to the database or the filesystem.
    """
    run = store.get_run(run_id)
    if run is None:
        raise ReplayError(f"no such run: {run_id}")
    envelope = store.get_claim_envelope(run_id)
    if envelope is None:
        raise ReplayError(f"run {run_id} has no stored input envelope")
    stored_records = store.get_results(run_id)
    provenance = {item.rule_id: item for item in store.get_explanations(run_id)}

    try:
        context = RuleContext.from_rules_dir(rules_dir)
    except RuleDirError as exc:
        raise ReplayError(f"the rule catalogue at {rules_dir} cannot be loaded: {exc}") from exc

    # The replay goes through the same path POST /v1/claims uses with no model
    # configured: the deterministic engine, then the explanation layer's
    # deterministic provider. Nothing is read from the stored records first.
    engine_records = [
        validate_record(record, envelope) for record in evaluate_claim(envelope, context)
    ]
    replayed = explain_run(
        engine_records, context, envelope, provider=TemplateExplanationProvider()
    )

    stored_by_rule = {record.rule_id: record.model_dump(mode="json") for record in stored_records}
    replayed_by_rule = {
        record.rule_id: record.model_dump(mode="json") for record in replayed.records
    }
    comparisons = tuple(
        compare_record(
            stored_by_rule.get(rule_id),
            replayed_by_rule.get(rule_id),
            provenance.get(rule_id),
        )
        for rule_id in dict.fromkeys([*stored_by_rule, *replayed_by_rule])
    )
    attention = tuple(record.rule_id for record in stored_records if requires_attention(record))

    return ReplayReport(
        run=run,
        database=_redact_dsn(resolve_dsn()),
        schema_revision=store.schema_revision(),
        catalogue=catalogue_identity(rules_dir, context),
        envelope_keys=len(envelope),
        stored_input_hash=run.input_hash,
        recomputed_input_hash=envelope_digest(envelope),
        comparisons=comparisons,
        chain=walk_run_chain(engine=engine, run=run, attention_rule_ids=attention),
    )


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------

#: What a verified replay establishes. Printed with every transcript, so a reader
#: never has to infer the scope of the claim from the code.
WHAT_THIS_PROVES: Final[tuple[str, ...]] = (
    "The 15 stored records are reproduced from the stored envelope alone: the "
    "replay recomputes status, severity, affected line ids, evidence pointers and "
    "corrective actions with the same deterministic engine and the same catalogue, "
    "then compares. No stored result is used as an input.",
    "The stored envelope is the one the ledger hashed: its canonical digest equals "
    "the run row's input_hash, and that hash also sits inside the hashed "
    "provenance code of the run's 'validated' event.",
    "The ledger rows for this run are intact and linked: each row's chain_hash "
    "recomputes from its own fields, each prev_hash is its predecessor's "
    "chain_hash, and the run event's versions and finding set agree with the run "
    "they describe.",
)

#: What it does not establish. The chain limit follows the pack's own wording,
#: stated in ``docs/12-Privacy-and-Security-Note.md`` §4.1.
WHAT_THIS_DOES_NOT_PROVE: Final[tuple[str, ...]] = (
    "It is not evidence that the checks are correct. Replay shows the same engine "
    "reaches the same answer on the same input; it says nothing about whether the "
    "fictional rulebook matches a payer's. A reproduced FAIL is a reproduced "
    "objection, not a denial.",
    "A reproduced PASS is not payment approval. PASS means 'this fictional "
    "rulebook raises no objection to this synthetic claim'.",
    "It is not proof against deletion or replacement of the whole log. A hash "
    "chain is tamper-EVIDENT: a row cut from the middle leaves a gap the link "
    "check detects, but the tail can be cut, the table dropped, or every row and "
    "every later hash rewritten into a self-consistent chain that no local check "
    "can refute — nothing outside the database pins the chain head (docs/12 §4.1).",
    "It does not prove the run was reviewed. Decisions live in "
    "claimguard.review_decisions; this replay shows them only as ledger events, "
    "and it neither replays nor endorses a reviewer's judgement.",
    "The data is synthetic teaching data. No claim here is real and nothing was "
    "submitted to a payer.",
)


def _wrap(prefix: str, text: str, width: int = 88) -> list[str]:
    """Wrap one bullet to the transcript width, deterministically."""
    indent = " " * len(prefix)
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = word if not current else f"{current} {word}"
        lead = prefix if not lines else indent
        if current and len(lead) + len(candidate) > width:
            lines.append((lead + current).rstrip())
            current = word
        else:
            current = candidate
    if current:
        lines.append(((prefix if not lines else indent) + current).rstrip())
    return lines


def render_transcript(report: ReplayReport) -> str:
    """Render the replay transcript (deterministic text; no wall-clock reading)."""
    total = len(report.comparisons)
    lines: list[str] = []
    lines.append("ClaimGuard audit replay — reconstructing one stored run from the ledger")
    lines.append("=" * 84)
    lines.append("Synthetic teaching data. This shows a past decision being reproduced;")
    lines.append("it is not evidence that the checks are correct.")
    lines.append("")
    lines.append(f"run_id         : {report.run.run_id}")
    lines.append(f"claim_id       : {report.run.claim_id}")
    lines.append(f"version        : {report.run.version}")
    lines.append(f"created_at     : {report.run.created_at.isoformat()}")
    lines.append(f"initiated_by   : {report.run.initiated_by}")
    lines.append(f"trace_id       : {report.run.trace_id}")
    lines.append("")
    lines.append(f"database       : {report.database} (schema revision {report.schema_revision})")
    lines.append(f"rules dir      : {report.catalogue.rules_dir}")
    lines.append(
        f"catalogue      : sha256 {report.catalogue.digest} "
        f"({report.catalogue.files} files, {report.catalogue.rules} rules)"
    )
    lines.append(f"rule_version   : {report.run.rule_version}")
    lines.append(f"model_version  : {report.run.model_version}")
    lines.append(f"prompt_version : {report.run.prompt_version}")
    lines.append("")

    lines.append("[1/4] stored input — the immutable envelope this run was made from")
    verdict = "MATCH" if report.hash_matches else "MISMATCH"
    lines.append(f"      stored input_hash : {report.stored_input_hash}")
    lines.append(f"      recomputed digest : {report.recomputed_input_hash}  [{verdict}]")
    lines.append(f"      envelope keys     : {report.envelope_keys}")
    lines.append("")

    lines.append("[2/4] replay — deterministic engine over the stored envelope, no model")
    lines.append("      rule  stored          engine fields  explanation")
    for comparison in report.comparisons:
        fields = (
            "all 14" if not comparison.differing_fields else ",".join(comparison.differing_fields)
        )
        lines.append(
            f"      {comparison.rule_id}  {comparison.stored_status:<14}  "
            f"{fields:<13}  {comparison.explanation}"
        )
    lines.append(
        f"      agreement : {report.agreements}/{total} records reproduced on all 14 engine fields"
    )
    for comparison in report.disagreements:
        detail = ", ".join(comparison.differing_fields) or comparison.explanation
        lines.append(f"      DISAGREEMENT {comparison.rule_id}: {detail}")
    lines.append("")

    lines.append("[3/4] ledger rows for this run — append-only, hash-chained")
    if not report.chain.events:
        lines.append("      no ledger rows for this run")
    for event in report.chain.events:
        decision = f" decision={event.decision}" if event.decision else ""
        findings = ",".join(event.finding_ids) or "-"
        lines.append(
            f"      #{event.index} {event.kind:<14} at={event.at} findings={findings}{decision}"
        )
        lines.append(f"          rule={event.rule_version} model={event.model_version}")
        lines.append(f"          event_id   {event.event_id}")
        lines.append(f"          prev_hash  {event.prev_hash}")
        lines.append(f"          chain_hash {event.chain_hash}")
    anchor = (
        f"row {report.chain.anchor_event_id}"
        if report.chain.anchor_event_id is not None
        else "genesis (this run's first event is the first row of the ledger)"
    )
    lines.append(f"      anchor  : {anchor}")
    lines.append(f"      hash    : {report.chain.anchor_hash}")
    intact = len(report.chain.events) - len(report.chain.content_broken)
    lines.append(f"      content : {intact}/{len(report.chain.events)} row hashes recompute")
    if report.chain.content_broken:
        lines.append(f"      UNLINKED: {', '.join(report.chain.content_broken)}")
    linkage = (
        "every row chains to its predecessor"
        if report.chain.link_broken_index is None
        else f"BROKEN at row #{report.chain.link_broken_index + 1}"
    )
    lines.append(f"      linkage : {linkage}")
    if report.chain.run_event_provenance:
        provenance = " ".join(
            f"{key}={value}" for key, value in report.chain.run_event_provenance.items()
        )
        agrees = "agrees with the run row" if not report.chain.run_event_mismatches else "differs"
        lines.append(f"      run event provenance: {provenance}  [{agrees}]")
    for mismatch in report.chain.run_event_mismatches:
        lines.append(f"      INCONSISTENT: {mismatch}")
    lines.append(f"      chain   : {'VERIFIED' if report.chain.ok else 'FAILED'}")
    lines.append("")

    lines.append("[4/4] verdict")
    lines.append(
        f"      input  : {'reproduced' if report.hash_matches else 'NOT reproduced'}"
        f" (the stored envelope is the hashed one)"
    )
    lines.append(f"      replay : {report.agreements}/{total} records reproduced")
    lines.append(f"      chain  : {'verified' if report.chain.ok else 'not verified'}")
    lines.append(f"      RESULT : {'PASS' if report.ok else 'FAIL'}")
    lines.append("")
    lines.append("WHAT THIS PROVES")
    for item in WHAT_THIS_PROVES:
        lines.extend(_wrap("  - ", item))
    lines.append("")
    lines.append("WHAT THIS DOES NOT PROVE")
    for item in WHAT_THIS_DOES_NOT_PROVE:
        lines.extend(_wrap("  - ", item))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """The replay's command line."""
    parser = argparse.ArgumentParser(
        prog="audit_replay",
        description=(
            "Replay one stored review run from its stored envelope and verify its "
            "audit-ledger rows (read-only)."
        ),
    )
    parser.add_argument("--run-id", required=True, help="the run to replay, e.g. RUN-<32 hex>")
    parser.add_argument(
        "--rules-dir",
        default=None,
        help=(
            "the rule catalogue to replay with; defaults to the same resolution the "
            "review API uses (CLAIMGUARD_RULES_DIR, then CLAIMGUARD_PACK_ROOT, then "
            "the vendored pack)"
        ),
    )
    return parser


def _resolve_rules_dir(explicit: str | None) -> Path:
    """The catalogue the replay runs with, or a refusal naming the setting to fix."""
    if explicit:
        candidate = Path(explicit)
        if not (candidate / RULE_FILE).is_file():
            raise ReplayError(f"no {RULE_FILE} in {candidate}")
        return candidate
    try:
        return resolve_rules_dir()
    except RuleDirError as exc:
        raise ReplayError(
            f"the rule catalogue is not resolvable: {exc}\n"
            "  point at it with CLAIMGUARD_RULES_DIR=<pack>/rules "
            "or CLAIMGUARD_PACK_ROOT=<pack>"
        ) from exc


def _open_store() -> tuple[ReviewStore, Engine]:
    """The review store and its engine, or a refusal naming the command that fixes it.

    The DSN comes from ``claimguard.config`` (``CLAIMGUARD_DATABASE_URL``), the
    same single source of truth the review API reads — a replay must run against
    the database the run was written to, so it is not a per-invocation argument.
    """
    dsn = resolve_dsn()
    engine = build_engine(dsn)
    store = ReviewStore(engine)
    try:
        revision = store.schema_revision()
    except SQLAlchemyError as exc:
        detail = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise ReplayError(
            f"the database is not reachable at {_redact_dsn(dsn)}: {detail}\n"
            "  start PostgreSQL:   docker compose up -d db\n"
            "  apply the schema:   uv run alembic upgrade head\n"
            "  point the app at it: CLAIMGUARD_DATABASE_URL="
            "postgresql+psycopg://claimguard:claimguard@localhost:5432/claimguard"
        ) from exc
    if revision is None:
        raise ReplayError(
            f"the review schema is not applied to {_redact_dsn(dsn)}: "
            "run `uv run alembic upgrade head` first"
        )
    return store, engine


def main(argv: Sequence[str] | None = None) -> int:
    """Run one replay, print the transcript, return the exit code."""
    args = build_parser().parse_args(argv)
    engine: Engine | None = None
    try:
        store, engine = _open_store()
        rules_dir = _resolve_rules_dir(args.rules_dir)
        report = replay_run(store=store, engine=engine, run_id=args.run_id, rules_dir=rules_dir)
    except ReplayError as exc:
        sys.stderr.write(f"audit replay refused: {exc}\n")
        return EXIT_REFUSED
    finally:
        if engine is not None:
            engine.dispose()
    _emit(render_transcript(report).rstrip("\n"))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
