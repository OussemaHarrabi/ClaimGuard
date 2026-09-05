"""Unit tests for the P0-3 hash-chain replica (``claimguard.audit.chain``).

These tests pin the contract that the Python replica must satisfy: genesis
handling, chaining, tamper detection (both link and content), NULL coercion
equivalence (``None`` == ``''``), the "raise on required-field None" guard,
and that field order changes the hash. Cross-language agreement with the SQL
trigger is enforced by the integration test (needs a live database).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from claimguard.audit.chain import GENESIS, AuditEvent, chain_hash, verify_chain

AT = datetime(2026, 9, 5, 12, 34, 56, 789012, tzinfo=UTC)
TRACE = "trace-0001"


def _event(
    *,
    prev_hash: str | None = None,
    at: datetime = AT,
    claim_ref: str | None = "CLM-0042",
    trace_id: str = TRACE,
    decision: str | None = None,
    reason_code: str | None = None,
    finding_ids: list[str] | None = None,
    model_version: str | None = "1.0",
    chain_hash_override: str | None = None,
) -> AuditEvent:
    """Build an audit event whose stored hash is correct by construction."""

    ids = finding_ids if finding_ids is not None else []
    prev = prev_hash if prev_hash is not None else GENESIS
    digest = chain_hash(prev, at, claim_ref, trace_id, decision, reason_code, ids, model_version)
    return {
        "at": at,
        "claim_ref": claim_ref,
        "trace_id": trace_id,
        "decision": decision,
        "reason_code": reason_code,
        "finding_ids": ids,
        "model_version": model_version,
        "prev_hash": prev,
        "chain_hash": chain_hash_override if chain_hash_override is not None else digest,
    }


def test_genesis_event_verifies() -> None:
    """A single event chained from 'genesis' is a valid chain."""

    events = [_event()]
    assert events[0]["prev_hash"] == GENESIS
    assert verify_chain(events) == (True, None)


def test_two_events_chain_together() -> None:
    """The second event must hash against the first event's chain_hash."""

    first = _event()
    second = _event(prev_hash=first["chain_hash"], trace_id="trace-0002")
    assert verify_chain([first, second]) == (True, None)
    # The second event's stored hash is exactly SHA256 of its serialization.
    assert second["chain_hash"] == chain_hash(
        second["prev_hash"],
        second["at"],
        second["claim_ref"],
        second["trace_id"],
        second["decision"],
        second["reason_code"],
        second["finding_ids"],
        second["model_version"],
    )


def test_tampered_stored_hash_is_detected() -> None:
    """A modified chain_hash (content tampering) is reported with its index."""

    first = _event()
    second = _event(prev_hash=first["chain_hash"], trace_id="trace-0002")
    third = _event(prev_hash=second["chain_hash"], trace_id="trace-0003")
    tampered: AuditEvent = {**second, "chain_hash": "0" + second["chain_hash"][1:]}
    assert verify_chain([first, tampered, third]) == (False, 1)


def test_tampered_prev_link_is_detected() -> None:
    """Rewriting prev_hash breaks the link and is reported with its index."""

    first = _event()
    second = _event(prev_hash=first["chain_hash"], trace_id="trace-0002")
    tampered: AuditEvent = {**second, "prev_hash": GENESIS}
    assert verify_chain([first, tampered]) == (False, 1)


def test_tampered_first_event_is_detected() -> None:
    """Rewriting the genesis event's stored hash is reported at index 0."""

    first = _event()
    second = _event(prev_hash=first["chain_hash"], trace_id="trace-0002")
    tampered: AuditEvent = {**first, "chain_hash": "f" + first["chain_hash"][1:]}
    assert verify_chain([tampered, second]) == (False, 0)


def test_none_coerces_to_empty_string() -> None:
    """NULL columns hash as '' — chain_hash(None, ...) == chain_hash('', ...)."""

    with_none = chain_hash(
        prev_hash=GENESIS,
        at=AT,
        claim_ref=None,
        trace_id=TRACE,
        decision=None,
        reason_code=None,
        finding_ids=[],
        model_version=None,
    )
    with_empty = chain_hash(
        prev_hash=GENESIS,
        at=AT,
        claim_ref="",
        trace_id=TRACE,
        decision="",
        reason_code="",
        finding_ids=[],
        model_version="",
    )
    assert with_none == with_empty
    # And the equivalence holds at the chain level (None == '' everywhere is
    # still a verifiable event).
    assert verify_chain([_event()]) == (True, None)


def test_field_order_changes_the_hash() -> None:
    """Swapping two hashed fields changes the digest — order is part of the contract.

    This is a property of `chain_hash` itself. `verify_chain` cannot detect it on
    its own, because a tamperer who edits a row can also recompute that row's
    hash — see the next test for what verification CAN and CANNOT prove.
    """
    straight = chain_hash(GENESIS, AT, "CLM-0042", TRACE, "A-001", "approve", [], "1.0")
    swapped = chain_hash(GENESIS, AT, "CLM-0042", TRACE, "approve", "A-001", [], "1.0")
    assert straight != swapped, "decision/reason_code order must affect the digest"


def test_forged_content_is_detected() -> None:
    """A row whose content is edited WITHOUT recomputing its hash is caught.

    This is the realistic tamper case the chain defends against: an accidental
    update, or an unsophisticated edit that forgets to recompute.
    """
    original = _event()
    forged = _event(
        decision="DENY-EVERYTHING",
        # Deliberately keep the ORIGINAL hash, as if someone edited the row
        # through a path that bypassed the trigger.
        chain_hash_override=original["chain_hash"],
    )
    assert forged["decision"] != original["decision"]
    assert verify_chain([forged]) == (False, 0)


def test_chain_detects_broken_link_but_not_full_recomputation() -> None:
    """Honest scope: the chain proves internal consistency, not impossibility.

    A tamperer with DB write access AND the trigger's algorithm can recompute
    every downstream hash and produce a self-consistent chain. Verification would
    pass. That is why the crypto-ledger bonus (BON-05) anchors daily Merkle roots
    to an independent location — see 04 §9 and 09 §Part C.
    """
    # Fully recomputed tampering is internally consistent, so it verifies.
    recomputed = _event(decision="TAMPERED-BUT-REHASHED")
    assert verify_chain([recomputed]) == (True, None)

    # But breaking the LINK is always caught.
    broken_link = _event(prev_hash="deadbeef")
    assert verify_chain([broken_link]) == (False, 0)


def test_required_fields_reject_none() -> None:
    """prev_hash / trace_id / at are NOT NULL columns: None must raise."""

    with pytest.raises(TypeError, match="prev_hash"):
        chain_hash(cast(str, None), AT, None, TRACE, None, None, [], None)
    with pytest.raises(TypeError, match="trace_id"):
        chain_hash(GENESIS, AT, None, cast(str, None), None, None, [], None)
    with pytest.raises(TypeError, match="at"):
        chain_hash(GENESIS, cast(datetime, None), None, TRACE, None, None, [], None)


def test_empty_chain_verifies() -> None:
    """No events is a trivially intact chain."""

    assert verify_chain([]) == (True, None)
