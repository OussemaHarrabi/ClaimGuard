"""Append-only audit trail for the review workflow (pack required behaviour 7).

WHAT THIS MODULE IS
-------------------
The write side of the existing, frozen audit ledger: run-level events and
decision-level events are appended to ``claimguard.audit_events`` — the
append-only, SHA-256 hash-chained table created by migration
``0001_initial_schema.sql`` and guarded by its trigger. Migration 0001 stays the
audit authority: this module never alters that table, never computes
``chain_hash``/``prev_hash`` (the trigger is the single canonical owner of the
hash serialisation — see :mod:`claimguard.audit.chain`) and never overrides them.

WHAT IT WRITES
--------------
One event per engine run and one per human decision — never one per finding.
Fifteen rows per claim would drown the ledger, and the run event already records
the finding set that matters.

============================  ===============================  ==========================
column                        run event (``validated``)        decision event
============================  ===============================  ==========================
``claim_ref``                 the run id (opaque)              the run id
``trace_id``                  the run's trace id               the run's trace id
``decision``                  NULL (no human decided)          the pack action
``reason_code``               provenance code (below)          NULL
``finding_ids``               rule ids needing attention       the reviewed rule id
``rule_version``              the rule catalogue version       the same
``model_version``             the model/prompt that ran        the same
============================  ===============================  ==========================

The 7-key pack review event's free-text ``reason`` is deliberately **not**
copied into the ledger. The ledger is the tamper-evident index of *what was done
with which versions*; reviewer free text may quote attachment content, and
duplicating it into an immutable table widens the data-protection surface for no
audit gain. It stays in ``claimguard.review_decisions``, reachable from the same
run id.

THE PROVENANCE CODE
-------------------
Migration 0001's table has no ``input_hash`` or ``prompt_version`` column, and it
is frozen. The run event therefore carries them, plus the initiating actor, in
``reason_code`` as a space-separated, ``key=value`` provenance descriptor::

    input_sha256=<64 hex> prompt_version=<version> actor=<who asked>

It is the only free structured text column, and it is part of the hashed payload
(the trigger concatenates ``... || decision || reason_code || ...``), so the claim
"this exact input version was checked with these versions, for this actor" is
itself tamper-evident. :func:`parse_provenance` reads it back; the rule and model
versions have their own columns.

CHAIN SAFETY (why the code below looks fussy)
---------------------------------------------
1.  ``at`` is inserted as ``clock_timestamp()``, not left to the column default.
    The default is ``now()``, which in PostgreSQL is the *transaction* start:
    two events appended by two concurrent transactions would then be ordered by
    timestamp differently from the order they were appended, and the chain —
    verified in ``(at, event_id)`` order by both
    ``claimguard.verify_audit_chain()`` and
    :func:`claimguard.audit.chain.verify_chain` — would report a broken link.
2.  The append takes a transaction-scoped advisory lock, because the 0001 trigger
    picks its predecessor with a plain ``SELECT ... ORDER BY at DESC, event_id
    DESC LIMIT 1``: two concurrent appenders could read the same predecessor and
    fork the chain. Serialising the review workflow's appends (additive; 0001 is
    untouched) removes that race. Append exactly one event per transaction:
    events sharing a transaction timestamp are ordered by their random
    ``event_id``, so batching them would make chain order depend on UUID luck.
3.  ``at::text`` renders in the *session* time zone, so every connection used by
    this workflow must run with ``TimeZone=UTC`` (``store.create_engine`` does
    this) or the trigger's hash and Python's replication disagree on every row.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy import Column, MetaData, Table, Text, insert, select, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.engine import Connection
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from claimguard.audit.chain import chain_hash
from claimguard.review.models import AuditStamp

#: Ledger ``kind`` values this workflow writes, from migration 0001's CHECK list.
#: ``validated`` is the lifecycle stage a rule run belongs to; ``review_decided``
#: is the pack's own name for a recorded human decision.
RUN_KIND: Final = "validated"
DECISION_KIND: Final = "review_decided"

#: Advisory-lock key for the audit append (arbitrary but fixed project constant).
AUDIT_APPEND_LOCK_KEY: Final = 0x636C61696D677561

#: ``key=value`` tokens of the provenance code, in a fixed order.
PROVENANCE_INPUT_KEY: Final = "input_sha256"
PROVENANCE_PROMPT_KEY: Final = "prompt_version"
PROVENANCE_ACTOR_KEY: Final = "actor"

_AUDIT_METADATA = MetaData()

#: Mapping of the EXISTING 0001 table (read + append). ``chain_hash`` and
#: ``prev_hash`` are mapped so they can be READ back, but this module never
#: supplies either on insert — the trigger owns both, and its BEFORE INSERT
#: assignment runs before the NOT NULL constraints are checked.
AUDIT_EVENTS = Table(
    "audit_events",
    _AUDIT_METADATA,
    Column("event_id", UUID(as_uuid=True), primary_key=True),
    Column("at", TIMESTAMP(timezone=True), nullable=False),
    Column("kind", Text, nullable=False),
    Column("claim_ref", Text),
    Column("trace_id", Text, nullable=False),
    Column("decision", Text),
    Column("reason_code", Text),
    Column("finding_ids", ARRAY(Text), nullable=False),
    Column("rule_version", Text),
    Column("model_version", Text),
    Column("prev_hash", Text, nullable=False),
    Column("chain_hash", Text, nullable=False),
    schema="claimguard",
)


@dataclass(frozen=True)
class AuditEventDraft:
    """One event to append, before the trigger assigns its hash."""

    kind: str
    claim_ref: str
    trace_id: str
    decision: str | None
    reason_code: str | None
    finding_ids: tuple[str, ...]
    rule_version: str | None
    model_version: str | None


@dataclass(frozen=True)
class AuditEventRow:
    """One ledger row as read back, including the chain link fields."""

    event_id: str
    at: datetime
    kind: str
    claim_ref: str | None
    trace_id: str
    decision: str | None
    reason_code: str | None
    finding_ids: tuple[str, ...]
    rule_version: str | None
    model_version: str | None
    prev_hash: str
    chain_hash: str


def format_provenance(*, input_hash: str, prompt_version: str, actor: str) -> str:
    """Render the run provenance code (``input_sha256=... prompt_version=... actor=...``)."""
    return (
        f"{PROVENANCE_INPUT_KEY}={input_hash} "
        f"{PROVENANCE_PROMPT_KEY}={prompt_version} "
        f"{PROVENANCE_ACTOR_KEY}={actor}"
    )


def parse_provenance(reason_code: str | None) -> dict[str, str]:
    """Read a provenance code back into its ``key`` -> ``value`` parts."""
    if not reason_code:
        return {}
    parts: dict[str, str] = {}
    for token in reason_code.split(" "):
        key, separator, value = token.partition("=")
        if separator:
            parts[key] = value
    return parts


def run_event(
    *,
    run_id: str,
    trace_id: str,
    input_hash: str,
    rule_version: str,
    model_version: str,
    prompt_version: str,
    actor: str,
    finding_ids: Iterable[str],
) -> AuditEventDraft:
    """The event that records one engine run over one claim version.

    ``finding_ids`` are the rule ids that need a human eye (see
    :func:`claimguard.review.models.requires_attention`), so the ledger shows
    which checks were escalated, not only that a run happened. ``actor`` is who
    asked for the run (``api-submit``, or the reviewer who requested a recheck):
    it rides in the hashed provenance code, because the ledger has no actor
    column and "who asked" is exactly the human-action half of behaviour 7.
    """
    return AuditEventDraft(
        kind=RUN_KIND,
        claim_ref=run_id,
        trace_id=trace_id,
        decision=None,
        reason_code=format_provenance(
            input_hash=input_hash, prompt_version=prompt_version, actor=actor
        ),
        finding_ids=tuple(finding_ids),
        rule_version=rule_version,
        model_version=model_version,
    )


def decision_event(
    *,
    run_id: str,
    trace_id: str,
    rule_id: str,
    action: str,
    rule_version: str,
    model_version: str,
) -> AuditEventDraft:
    """The event that records one human decision about one finding of one run."""
    return AuditEventDraft(
        kind=DECISION_KIND,
        claim_ref=run_id,
        trace_id=trace_id,
        decision=action,
        reason_code=None,
        finding_ids=(rule_id,),
        rule_version=rule_version,
        model_version=model_version,
    )


def append(connection: Connection, draft: AuditEventDraft) -> AuditStamp:
    """Append ``draft`` to the chain and return the stamp the trigger produced.

    MUST be called inside an open transaction (``engine.begin()``): the advisory
    lock is transaction-scoped, which is what makes the lock and the insert
    atomic with respect to other appenders.
    """
    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": AUDIT_APPEND_LOCK_KEY})
    row = connection.execute(
        insert(AUDIT_EVENTS)
        .values(
            event_id=uuid.uuid4(),
            at=func.clock_timestamp(),
            kind=draft.kind,
            claim_ref=draft.claim_ref,
            trace_id=draft.trace_id,
            decision=draft.decision,
            reason_code=draft.reason_code,
            finding_ids=list(draft.finding_ids),
            rule_version=draft.rule_version,
            model_version=draft.model_version,
        )
        .returning(AUDIT_EVENTS.c.event_id, AUDIT_EVENTS.c.at, AUDIT_EVENTS.c.chain_hash)
    ).one()
    return AuditStamp(
        event_id=str(row.event_id),
        at=row.at,
        kind=draft.kind,
        chain_hash=str(row.chain_hash),
    )


def events_for_ref(connection: Connection, claim_ref: str) -> list[AuditEventRow]:
    """Every ledger row for one opaque reference (a run id), in chain order."""
    rows = connection.execute(
        select(AUDIT_EVENTS)
        .where(AUDIT_EVENTS.c.claim_ref == claim_ref)
        .order_by(AUDIT_EVENTS.c.at, AUDIT_EVENTS.c.event_id)
    ).all()
    return [
        AuditEventRow(
            event_id=str(row.event_id),
            at=row.at,
            kind=str(row.kind),
            claim_ref=row.claim_ref,
            trace_id=str(row.trace_id),
            decision=row.decision,
            reason_code=row.reason_code,
            finding_ids=tuple(str(item) for item in (row.finding_ids or ())),
            rule_version=row.rule_version,
            model_version=row.model_version,
            prev_hash=str(row.prev_hash),
            chain_hash=str(row.chain_hash),
        )
        for row in rows
    ]


def unlinked_refs(connection: Connection, claim_refs: Sequence[str]) -> dict[str, list[str]]:
    """Recompute each event's chain hash; report the events that do not verify.

    Read-only, and the same check ``claimguard.verify_audit_chain()`` performs for
    the whole table: an event's stored ``chain_hash`` must equal a fresh
    recomputation of its own fields through
    :func:`claimguard.audit.chain.chain_hash` (the trigger's character-for-
    character replica). Works on a slice of the chain, so a test can verify its
    own events without owning the whole ledger.

    Returns ``{claim_ref: [event_id, ...]}``; an empty mapping means every event
    of every requested reference is intact.
    """
    broken: dict[str, list[str]] = {}
    for ref in claim_refs:
        for row in events_for_ref(connection, ref):
            recomputed = chain_hash(
                prev_hash=row.prev_hash,
                at=row.at,
                claim_ref=row.claim_ref,
                trace_id=row.trace_id,
                decision=row.decision,
                reason_code=row.reason_code,
                finding_ids=list(row.finding_ids),
                model_version=row.model_version,
            )
            if recomputed != row.chain_hash:
                broken.setdefault(ref, []).append(row.event_id)
    return broken


def provenance_of(row: AuditEventRow) -> Mapping[str, str]:
    """The parsed provenance code of a run event (empty for other kinds)."""
    return parse_provenance(row.reason_code)
