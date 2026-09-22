"""Integration tests: persistence, the review queue and the audit chain.

**These tests need PostgreSQL** (skipped automatically when it is unreachable;
see ``tests/review/__init__.py``). They run against the real schema created by
``0002_review_workflow.sql`` — the same tables production uses — because the
invariants under test are database invariants (immutable runs, append-only
decisions, and an audit link the trigger computes).

Every test removes the rows it created (the ``sandbox`` fixture), so the database
is left as it was found.
"""

from __future__ import annotations

from typing import Any

import pytest
from claimguard.edu.emit import serialize
from claimguard.edu.engine import evaluate_claim
from claimguard.edu.envelope import RULE_VERSION, ResultRecord, Severity, Status
from claimguard.edu.policy import RuleContext
from claimguard.review import audit_events
from claimguard.review.models import (
    ClaimQueueSummary,
    DecisionRequest,
    IllegalReviewTransitionError,
    QueueFilters,
    ReviewAction,
    ReviewState,
    ReviewStatus,
)
from claimguard.review.store import (
    FindingNotFoundError,
    NoCorrectionError,
    ReviewStore,
    RunNotFoundError,
    RunSupersededError,
    envelope_digest,
)
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests.edu import RULES_DIR
from tests.review.conftest import FAILING_RULE, Sandbox, requires_db

pytestmark = [pytest.mark.integration, requires_db]

MODEL_VERSION = "deterministic-engine/1.0.0"
PROMPT_VERSION = "none"


def records_for(envelope: dict[str, Any]) -> list[ResultRecord]:
    """The engine's own records for an envelope, in R001..R015 order."""
    context = RuleContext.from_rules_dir(RULES_DIR)
    return [ResultRecord.model_validate(record) for record in evaluate_claim(envelope, context)]


def submit(store: ReviewStore, envelope: dict[str, Any], **kwargs: Any) -> Any:
    """Persist a first version of a claim the way the API does."""
    return store.record_run(
        envelope,
        records_for(envelope),
        rule_version=RULE_VERSION,
        model_version=MODEL_VERSION,
        prompt_version=PROMPT_VERSION,
        initiated_by=kwargs.pop("initiated_by", "test-submit"),
    )


def recheck(store: ReviewStore, envelope: dict[str, Any], **kwargs: Any) -> Any:
    """Persist a corrected envelope as a new version, the way the API does."""
    return store.record_recheck(
        envelope,
        records_for(envelope),
        rule_version=RULE_VERSION,
        model_version=MODEL_VERSION,
        prompt_version=PROMPT_VERSION,
        initiated_by=kwargs.pop("initiated_by", "rev-1"),
    )


def decide(store: ReviewStore, run_id: str, action: ReviewAction, **kwargs: Any) -> Any:
    """Record one decision with a valid actor and reason."""
    return store.record_decision(
        run_id,
        DecisionRequest(
            rule_id=kwargs.pop("rule_id", FAILING_RULE),
            action=action,
            actor=kwargs.pop("actor", "rev-1"),
            reason=kwargs.pop("reason", "checked against the source record"),
        ),
    )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def test_a_run_persists_the_fifteen_records_and_its_identity(
    store: ReviewStore, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    recorded = submit(store, envelope)

    assert recorded.duplicate is False
    assert recorded.run.version == 1
    assert recorded.run.claim_id == envelope["claim_id"]
    assert recorded.run.input_hash == envelope_digest(envelope)
    assert recorded.run.rule_version == RULE_VERSION
    assert recorded.run.model_version == MODEL_VERSION
    assert recorded.run.prompt_version == PROMPT_VERSION
    assert recorded.run.initiated_by == "test-submit"
    assert recorded.run.supersedes_run_id is None
    assert len(recorded.run.trace_id) == 32

    stored = store.get_results(recorded.run.run_id)
    assert [record.rule_id for record in stored] == [f"R{index:03d}" for index in range(1, 16)]
    assert stored == records_for(envelope)
    assert [json_of(record) for record in stored] == [
        serialize(record.model_dump(), envelope) for record in stored
    ], "stored records must still satisfy the frozen result contract"
    assert store.latest_run(envelope["claim_id"]) == recorded.run
    assert recorded.needs_attention == 1


def json_of(record: ResultRecord) -> str:
    """The record's canonical JSON, for equality across a database round-trip."""
    return serialize(record.model_dump())


def test_an_identical_resubmission_is_not_a_new_version(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    first = submit(store, envelope)
    again = submit(store, envelope)

    assert again.duplicate is True
    assert again.run.run_id == first.run.run_id
    assert len(store.list_runs(envelope["claim_id"])) == 1
    with engine.connect() as connection:
        assert len(audit_events.events_for_ref(connection, first.run.run_id)) == 1


def test_a_correction_is_a_new_version_and_leaves_the_original_untouched(
    store: ReviewStore, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    first = submit(store, envelope)
    original_records = store.get_results(first.run.run_id)

    corrected = sandbox.corrected(envelope)
    second = recheck(store, corrected)

    assert second.run.version == 2
    assert second.run.supersedes_run_id == first.run.run_id
    assert second.run.input_hash != first.run.input_hash
    versions = store.list_runs(envelope["claim_id"])
    assert [run.version for run in versions] == [1, 2]

    assert store.get_results(first.run.run_id) == original_records, "the original run changed"
    original_r003 = next(r for r in original_records if r.rule_id == FAILING_RULE)
    corrected_r003 = next(
        r for r in store.get_results(second.run.run_id) if r.rule_id == FAILING_RULE
    )
    assert original_r003.status is Status.FAIL
    assert corrected_r003.status is Status.PASS
    assert store.latest_run(envelope["claim_id"]) == second.run


def test_a_recheck_needs_a_real_correction(store: ReviewStore, sandbox: Sandbox) -> None:
    envelope = sandbox.coverage_lapse()
    submit(store, envelope)
    with pytest.raises(NoCorrectionError):
        recheck(store, envelope)


def test_a_recheck_of_an_unknown_claim_is_refused(store: ReviewStore, sandbox: Sandbox) -> None:
    with pytest.raises(RunNotFoundError):
        recheck(store, sandbox.corrected(sandbox.coverage_lapse()))


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


def test_the_queue_defaults_to_the_checks_that_need_a_human(
    store: ReviewStore, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    submit(store, envelope)

    queue = store.queue(QueueFilters(claim_id=envelope["claim_id"]))
    assert [item.record.rule_id for item in queue.items] == [FAILING_RULE]
    assert queue.counts.findings == 1
    assert queue.counts.unresolved == 1
    assert queue.counts.resolved == 0
    assert queue.counts.by_rule_status[Status.FAIL.value] == 1
    assert queue.counts.by_review_status == {ReviewStatus.UNREVIEWED.value: 1}
    assert queue.counts.by_severity == {"high": 1}
    assert queue.claims == [
        ClaimQueueSummary(
            claim_id=envelope["claim_id"],
            run_id=queue.items[0].run_id,
            version=1,
            findings=1,
            unresolved=1,
        )
    ]

    everything = store.queue(QueueFilters(claim_id=envelope["claim_id"], include_all=True))
    assert len(everything.items) == 15
    assert everything.counts.findings == 15
    assert everything.counts.unresolved == 15
    assert everything.counts.by_rule_status["PASS"] == 11
    assert everything.counts.by_rule_status["NOT_APPLICABLE"] == 3
    assert everything.counts.by_review_status == {ReviewStatus.UNREVIEWED.value: 15}


def test_queue_filters_narrow_by_rule_severity_and_status(
    store: ReviewStore, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    submit(store, envelope)
    claim_id = envelope["claim_id"]

    by_rule = store.queue(QueueFilters(claim_id=claim_id, rule_id=FAILING_RULE))
    assert len(by_rule.items) == 1
    assert store.queue(QueueFilters(claim_id=claim_id, rule_id="R004")).items == []

    by_severity = store.queue(QueueFilters(claim_id=claim_id, severity=Severity.LOW))
    assert by_severity.items == []
    assert len(store.queue(QueueFilters(claim_id=claim_id, severity=Severity.HIGH)).items) == 1

    by_status = store.queue(QueueFilters(claim_id=claim_id, status=Status.PASS, include_all=True))
    assert len(by_status.items) == 11
    assert all(item.record.status is Status.PASS for item in by_status.items)

    assert store.queue(QueueFilters(claim_id="CG-NOT-SUBMITTED")).items == []


def test_the_queue_reports_unresolved_checks_until_they_are_decided(
    store: ReviewStore, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    run = submit(store, envelope).run
    claim_id = envelope["claim_id"]

    assert store.queue(QueueFilters(claim_id=claim_id)).counts.unresolved == 1
    decide(store, run.run_id, ReviewAction.REQUEST_INFORMATION)
    asked = store.queue(QueueFilters(claim_id=claim_id))
    assert asked.counts.unresolved == 1
    assert asked.counts.resolved == 0
    assert asked.items[0].review.status is ReviewStatus.INFO_REQUESTED

    decide(store, run.run_id, ReviewAction.CONFIRM_ISSUE, reason="the answer arrived")
    answered = store.queue(QueueFilters(claim_id=claim_id))
    assert answered.counts.unresolved == 0
    assert answered.counts.resolved == 1
    assert answered.claims[0].latest_decision_at is not None


def test_the_queue_shows_the_current_version_only(store: ReviewStore, sandbox: Sandbox) -> None:
    envelope = sandbox.coverage_lapse()
    first = submit(store, envelope).run
    decide(store, first.run_id, ReviewAction.CONFIRM_ISSUE)

    second = recheck(store, sandbox.corrected(envelope)).run
    queue = store.queue(QueueFilters(claim_id=envelope["claim_id"], include_all=True))
    assert {item.run_id for item in queue.items} == {second.run_id}
    assert all(item.version == 2 for item in queue.items)

    superseded = store.queue(QueueFilters(claim_id=envelope["claim_id"]))
    assert [item.record.status for item in superseded.items] == []
    assert superseded.counts.unresolved == 0


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


def test_a_decision_records_the_pack_event_the_state_and_the_history(
    store: ReviewStore, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    run = submit(store, envelope).run
    recorded = decide(store, run.run_id, ReviewAction.CONFIRM_ISSUE, actor="rev-7", reason="proven")

    event = recorded.decision.event
    assert tuple(event.to_event()) == (
        "claim_id",
        "rule_id",
        "action",
        "actor",
        "reason",
        "created_at",
        "original_status",
    )
    assert event.claim_id == envelope["claim_id"]
    assert event.rule_id == FAILING_RULE
    assert event.action is ReviewAction.CONFIRM_ISSUE
    assert event.actor == "rev-7"
    assert event.reason == "proven"
    assert event.original_status is Status.FAIL, "original_status is the finding's rule status"
    assert recorded.decision.run_id == run.run_id
    assert recorded.review == ReviewState(
        status=ReviewStatus.CONFIRMED,
        action=ReviewAction.CONFIRM_ISSUE,
        actor="rev-7",
        reason="proven",
        decided_at=event.created_at,
        decision_count=1,
    )

    assert store.get_decisions(run.run_id) == [recorded.decision]
    history = store.decision_history(run.run_id)
    assert history.run_id == run.run_id
    assert [entry.decision for entry in history.entries] == [recorded.decision]
    assert history.entries[0].review.status is ReviewStatus.CONFIRMED


def test_the_store_enforces_the_decision_state_machine(
    store: ReviewStore, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    run = submit(store, envelope).run

    decide(store, run.run_id, ReviewAction.DISMISS_WITH_REASON, reason="attachment proves it")
    with pytest.raises(IllegalReviewTransitionError):
        decide(store, run.run_id, ReviewAction.CONFIRM_ISSUE)
    with pytest.raises(IllegalReviewTransitionError):
        decide(store, run.run_id, ReviewAction.DISMISS_WITH_REASON)

    reopened = decide(store, run.run_id, ReviewAction.REQUEST_INFORMATION)
    assert reopened.review.status is ReviewStatus.INFO_REQUESTED
    assert reopened.review.decision_count == 2
    assert decide(store, run.run_id, ReviewAction.CONFIRM_ISSUE).review.decision_count == 3


def test_a_decision_on_a_superseded_version_is_refused(
    store: ReviewStore, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    first = submit(store, envelope).run
    recheck(store, sandbox.corrected(envelope))
    with pytest.raises(RunSupersededError):
        decide(store, first.run_id, ReviewAction.CONFIRM_ISSUE)


def test_unknown_runs_and_findings_are_reported(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    run = submit(store, envelope).run
    with pytest.raises(RunNotFoundError):
        decide(store, "RUN-does-not-exist", ReviewAction.CONFIRM_ISSUE)

    # A finding that is not there (a partially restored dataset) is reported, never
    # silently decided about — the pack requires a decision to name a real check.
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DELETE FROM claimguard.rule_results WHERE run_id = %s AND rule_id = %s",
            (run.run_id, "R014"),
        )
    with pytest.raises(FindingNotFoundError):
        decide(store, run.run_id, ReviewAction.CONFIRM_ISSUE, rule_id="R014")
    assert decide(store, run.run_id, ReviewAction.CONFIRM_ISSUE).review.status is (
        ReviewStatus.CONFIRMED
    )


# ---------------------------------------------------------------------------
# The audit chain
# ---------------------------------------------------------------------------


def test_run_and_decision_events_land_in_the_hash_chained_ledger(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    recorded = submit(store, envelope)
    decision = decide(store, recorded.run.run_id, ReviewAction.CONFIRM_ISSUE)

    with engine.connect() as connection:
        rows = audit_events.events_for_ref(connection, recorded.run.run_id)
        assert [row.kind for row in rows] == [audit_events.RUN_KIND, audit_events.DECISION_KIND]
        run_event, decision_event = rows

        assert run_event.claim_ref == recorded.run.run_id
        assert run_event.trace_id == recorded.run.trace_id
        assert run_event.rule_version == RULE_VERSION
        assert run_event.model_version == MODEL_VERSION
        assert run_event.finding_ids == (FAILING_RULE,)
        assert run_event.decision is None
        provenance = audit_events.parse_provenance(run_event.reason_code)
        assert provenance["input_sha256"] == envelope_digest(envelope)
        assert provenance["prompt_version"] == PROMPT_VERSION
        assert provenance["actor"] == "test-submit"

        assert decision_event.decision == ReviewAction.CONFIRM_ISSUE.value
        assert decision_event.finding_ids == (FAILING_RULE,)
        assert decision_event.claim_ref == recorded.run.run_id
        assert decision_event.trace_id == recorded.run.trace_id

        # Links: the second event chains the first, and the first chains whatever
        # was in the ledger before it (we append; we never fork or re-hash).
        assert decision_event.prev_hash == run_event.chain_hash
        assert run_event.prev_hash == ledger_predecessor(
            connection, run_event.at, run_event.event_id
        )
        assert audit_events.unlinked_refs(connection, [recorded.run.run_id]) == {}

    assert recorded.audit.chain_hash == run_event.chain_hash
    assert decision.audit.chain_hash == decision_event.chain_hash
    assert decision.audit.kind == audit_events.DECISION_KIND


def ledger_predecessor(connection: Any, at: Any, event_id: str) -> str:
    """The chain hash of the ledger row that precedes ``(at, event_id)``."""
    row = connection.execute(
        text(
            "SELECT chain_hash FROM claimguard.audit_events "
            "WHERE (at, event_id) < (:at, :event_id) ORDER BY at DESC, event_id DESC LIMIT 1"
        ),
        {"at": at, "event_id": event_id},
    ).one_or_none()
    return str(row.chain_hash) if row is not None else "genesis"


def test_the_sql_verifier_finds_no_break_at_our_events(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    """``claimguard.verify_audit_chain()`` must not report one of our rows."""
    envelope = sandbox.coverage_lapse()
    recorded = submit(store, envelope)
    decide(store, recorded.run.run_id, ReviewAction.CONFIRM_ISSUE)

    with engine.connect() as connection:
        mine = {
            event.event_id for event in audit_events.events_for_ref(connection, recorded.run.run_id)
        }
        broken = {
            str(row.event_id)
            for row in connection.execute(
                text("SELECT event_id FROM claimguard.verify_audit_chain()")
            )
        }
    assert mine
    assert mine & broken == set()


def test_every_ledger_event_carries_the_versions_it_ran_with(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    """Behaviour 7: checks and human actions are recorded with rule/model versions."""
    envelope = sandbox.coverage_lapse()
    recorded = submit(store, envelope)
    decide(store, recorded.run.run_id, ReviewAction.MARK_CORRECTED_FOR_RECHECK, reason="corrected")
    recheck(store, sandbox.corrected(envelope))

    with engine.connect() as connection:
        events = [
            event
            for run in store.list_runs(envelope["claim_id"])
            for event in audit_events.events_for_ref(connection, run.run_id)
        ]
    assert len(events) == 3
    assert all(event.rule_version == RULE_VERSION for event in events)
    assert all(event.model_version == MODEL_VERSION for event in events)
    assert {event.kind for event in events} == {audit_events.RUN_KIND, audit_events.DECISION_KIND}
    recheck_event = events[-1]
    assert audit_events.parse_provenance(recheck_event.reason_code)["actor"] == "rev-1"


# ---------------------------------------------------------------------------
# Database-level guards
# ---------------------------------------------------------------------------


def test_a_run_row_cannot_be_updated(store: ReviewStore, engine: Engine, sandbox: Sandbox) -> None:
    run = submit(store, sandbox.coverage_lapse()).run
    with pytest.raises(DBAPIError) as refusal, engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE claimguard.rule_runs SET input_hash = %s WHERE run_id = %s",
            ("0" * 64, run.run_id),
        )
    assert "immutable" in str(refusal.value)


def test_a_result_record_cannot_be_updated(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    run = submit(store, sandbox.coverage_lapse()).run
    with pytest.raises(DBAPIError) as refusal, engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE claimguard.rule_results SET status = 'PASS' WHERE run_id = %s",
            (run.run_id,),
        )
    assert "immutable" in str(refusal.value)


def test_a_decision_cannot_be_updated_or_deleted(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    run = submit(store, sandbox.coverage_lapse()).run
    recorded = decide(store, run.run_id, ReviewAction.CONFIRM_ISSUE, reason="original wording")
    for statement in (
        "UPDATE claimguard.review_decisions SET reason = 'rewritten' WHERE run_id = %s",
        "DELETE FROM claimguard.review_decisions WHERE run_id = %s",
    ):
        with pytest.raises(DBAPIError) as refusal, engine.begin() as connection:
            connection.exec_driver_sql(statement, (run.run_id,))
        assert "immutable" in str(refusal.value)
    assert store.get_decisions(run.run_id) == [recorded.decision], "the row was really untouched"


def test_the_session_timezone_is_utc_on_every_connection(engine: Engine) -> None:
    """The audit trigger hashes ``at::text``; a non-UTC session breaks every link."""
    for _ in range(3):
        with engine.connect() as connection:
            assert connection.execute(text("SHOW TimeZone")).scalar() == "UTC"
            connection.execute(text("SELECT 1")).scalar()
        with engine.begin() as connection:
            connection.execute(text("SELECT 1")).scalar()
    with engine.connect() as connection:
        assert connection.execute(text("SHOW TimeZone")).scalar() == "UTC"
