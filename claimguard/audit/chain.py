"""SHA-256 hash chain for ``claimguard.audit_events`` (P0-3 contract).

CONTRACT
--------
The PostgreSQL insert trigger ``claimguard.audit_chain_insert()`` (migration
``0001_initial_schema.sql``) is the **single canonical owner** of the hash
serialisation. This module replicates it character-for-character. Both must
use EXACTLY this field list, in this order, with NO separator, NULLs coerced
to the empty string:

    prev_hash || at::text || COALESCE(claim_ref::text,'') || trace_id
    || COALESCE(decision,'') || COALESCE(reason_code,'')
    || COALESCE(array_to_string(finding_ids, ','),'') || COALESCE(model_version,'')

Broken down:

* fields concatenated with **no separator** (PostgreSQL ``||``);
* NULL columns become ``''`` (``COALESCE(col, '')``) — ``None`` here is
  equivalent to ``""``;
* ``finding_ids`` is joined with ``","`` (``array_to_string(finding_ids, ',')``);
* the genesis event uses ``prev_hash = 'genesis'``;
* the digest is the lowercase hex SHA-256 of the UTF-8 encoding of the
  concatenation.

**WARNING: ANY change to the field list, their order, the separator, the NULL
coercion or the list join MUST be mirrored in the SQL trigger
``claimguard.audit_chain_insert()`` (and in ``claimguard.verify_audit_chain()``)
at the same time**, or chain verification will report broken links. The field
list is a schema migration, not a local edit.

Chain order
-----------
Events are chained in ``(at, event_id)`` order. :func:`verify_chain` expects
its input already in that order (``SELECT ... ORDER BY at, event_id``) — the
same ordering the trigger uses when it picks the previous event and the SQL
``claimguard.verify_audit_chain()`` uses when it walks the chain.

Cross-language note
-------------------
``at::text`` renders the timestamp in the *session* time zone. For the Python
hash to agree with the trigger bit-for-bit, application database connections
MUST run with ``TimeZone`` set to ``UTC`` — this module formats ``at`` as UTC
using PostgreSQL's exact textual rendering (space separator, 6-digit
fractional seconds, ``+00`` offset).

Required fields
---------------
``prev_hash`` and ``trace_id`` are ``NOT NULL`` in the database and are never
``COALESCE``-d by the trigger, so a ``None`` there is a caller bug and raises
``TypeError``. The nullable fields (``claim_ref``, ``decision``,
``reason_code``, ``model_version``) coerce ``None`` to ``""`` exactly like the
trigger.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TypedDict

#: ``prev_hash`` of the first event of the chain (mirrors the trigger's
#: ``COALESCE(previous, 'genesis')``).
GENESIS = "genesis"


class AuditEvent(TypedDict):
    """One row of ``claimguard.audit_events``, in chain order (``at, event_id``)."""

    at: datetime
    claim_ref: str | None
    trace_id: str
    decision: str | None
    reason_code: str | None
    finding_ids: list[str]
    model_version: str | None
    prev_hash: str
    chain_hash: str


def _coalesce(value: str | None) -> str:
    """Mirror PostgreSQL ``COALESCE(col, '')`` for a nullable text column."""

    return value if value is not None else ""


def _at_text(at: datetime) -> str:
    """Render ``at`` exactly as PostgreSQL renders ``timestamptz::text`` (UTC session).

    PostgreSQL's text output for timestamptz is:
        'YYYY-MM-DD HH:MM:SS[.ffffff]+00'

    ...where the fractional part is OMITTED entirely when it is zero, and is
    otherwise emitted without trailing-zero padding. This matters because the
    hash is over ``at::text``: a mismatch of one character breaks every link.

    Discovered by the live-DB parity test: Python's ``%f`` always emits six
    digits ('00:00:00.000000'), while Postgres emits '00:00:00' for a whole
    second. That single difference made the two implementations disagree on
    every timestamp without fractional part.

    Requires the database session to run with TimeZone=UTC (see module docstring).
    """

    at_utc = at.astimezone(UTC)
    base = at_utc.strftime("%Y-%m-%d %H:%M:%S")
    microsecond = at_utc.microsecond
    if microsecond:
        # Match Postgres: strip trailing zeros from the fractional part.
        fraction = f"{microsecond:06d}".rstrip("0")
        return f"{base}.{fraction}+00"
    return f"{base}+00"


def chain_hash(
    prev_hash: str,
    at: datetime,
    claim_ref: str | None,
    trace_id: str,
    decision: str | None,
    reason_code: str | None,
    finding_ids: list[str],
    model_version: str | None,
) -> str:
    """Replicate ``claimguard.audit_chain_insert()`` character-for-character.

    Returns the lowercase-hex SHA-256 of the UTF-8 encoding of
    ``prev_hash + at + claim_ref + trace_id + decision + reason_code +
    finding_ids(comma-joined) + model_version`` with the NULL coercion rules
    described in the module docstring.

    Raises ``TypeError`` when a required (database ``NOT NULL``) field is
    ``None``; ``None`` on a nullable field is legal and hashes as ``""``.
    """

    # Runtime guards: the type checker proves these cannot be None for typed
    # callers, but untyped callers / dict-decoded rows can still pass None —
    # the database would reject those columns too, so fail loudly here.
    if prev_hash is None:  # type: ignore[reportUnnecessaryComparison]
        raise TypeError("prev_hash must not be None (required: PostgreSQL NOT NULL)")
    if at is None:  # type: ignore[reportUnnecessaryComparison]
        raise TypeError("at must not be None (required: PostgreSQL NOT NULL)")
    if trace_id is None:  # type: ignore[reportUnnecessaryComparison]
        raise TypeError("trace_id must not be None (required: PostgreSQL NOT NULL)")

    serialized = "".join(
        [
            prev_hash,
            _at_text(at),
            _coalesce(claim_ref),
            trace_id,
            _coalesce(decision),
            _coalesce(reason_code),
            ",".join(finding_ids),
            _coalesce(model_version),
        ]
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def verify_chain(events: Sequence[AuditEvent]) -> tuple[bool, int | None]:
    """Walk a hash chain and locate the first broken link, if any.

    ``events`` MUST be in chain order (``ORDER BY at, event_id``), the same
    order used by the SQL verifier ``claimguard.verify_audit_chain()``.

    Mirrors the SQL logic exactly: for each event, the expected ``prev_hash``
    is the previous event's stored ``chain_hash`` (starting from ``GENESIS``),
    and the stored ``chain_hash`` must equal a fresh recomputation of the
    event's own fields.

    Returns ``(True, None)`` when the chain is intact, otherwise
    ``(False, index)`` where ``index`` is the position of the first event
    whose link or content does not verify.
    """

    previous = GENESIS
    for index, event in enumerate(events):
        if event["prev_hash"] != previous:
            return False, index
        recomputed = chain_hash(
            prev_hash=event["prev_hash"],
            at=event["at"],
            claim_ref=event["claim_ref"],
            trace_id=event["trace_id"],
            decision=event["decision"],
            reason_code=event["reason_code"],
            finding_ids=event["finding_ids"],
            model_version=event["model_version"],
        )
        if recomputed != event["chain_hash"]:
            return False, index
        previous = event["chain_hash"]
    return True, None
