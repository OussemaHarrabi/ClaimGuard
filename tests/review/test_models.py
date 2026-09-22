"""Unit tests for the review contracts and the decision state machine.

No database, no network: this module always runs (CI included). It pins the parts
of the review surface that must not drift — the pack's 7-key ``review_event``
contract, the four-action state machine, the queue's notion of "needs attention",
and the run identity model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from claimguard.edu.envelope import RESULT_KEYS, ResultRecord, Status
from claimguard.review.models import (
    ALLOWED_TRANSITIONS,
    REVIEW_ACTIONS,
    REVIEW_EVENT_KEYS,
    REVIEW_STATUSES,
    IllegalReviewTransitionError,
    ReviewAction,
    ReviewDecisionEvent,
    ReviewState,
    ReviewStatus,
    RuleRun,
    is_unresolved,
    next_status,
    requires_attention,
    summarize_statuses,
)
from pydantic import ValidationError

from tests.edu import all_statuses, base_claim, record

pytestmark = pytest.mark.unit

HASH = "a" * 64
TRACE = "b" * 32


def event(**overrides: Any) -> dict[str, Any]:
    """A valid pack review event, with overrides applied."""
    payload: dict[str, Any] = {
        "claim_id": "CG-TEST-0001",
        "rule_id": "R003",
        "action": "confirm_issue",
        "actor": "rev-1",
        "reason": "coverage period proven against the source record",
        "created_at": "2026-03-21T10:00:00+00:00",
        "original_status": "FAIL",
    }
    payload.update(overrides)
    return payload


def run(**overrides: Any) -> dict[str, Any]:
    """A valid run record, with overrides applied."""
    payload: dict[str, Any] = {
        "run_id": "RUN-0123456789abcdef0123456789abcdef",
        "claim_id": "CG-TEST-0001",
        "version": 1,
        "input_hash": HASH,
        "trace_id": TRACE,
        "rule_version": "1.0.0",
        "model_version": "deterministic-engine/1.0.0",
        "prompt_version": "none",
        "initiated_by": "api-submit",
        "created_at": "2026-03-21T10:00:00+00:00",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# The pack's 7-key review event
# ---------------------------------------------------------------------------


def test_event_has_exactly_the_packs_seven_keys() -> None:
    parsed = ReviewDecisionEvent.model_validate(event())
    assert tuple(parsed.to_event()) == REVIEW_EVENT_KEYS
    assert tuple(parsed.model_dump()) == REVIEW_EVENT_KEYS
    assert set(parsed.to_event()) == {
        "claim_id",
        "rule_id",
        "action",
        "actor",
        "reason",
        "created_at",
        "original_status",
    }


def test_event_renders_created_at_as_the_pack_types_it() -> None:
    """``schemas/review_event.schema.json`` types ``created_at`` as a string."""
    rendered = ReviewDecisionEvent.model_validate(event()).to_event()
    assert isinstance(rendered["created_at"], str)
    assert rendered["created_at"].startswith("2026-03-21T10:00:00")


def test_event_round_trips_through_its_serialized_form() -> None:
    payload = event()
    assert ReviewDecisionEvent.from_event(payload).to_event() == {
        **payload,
        "created_at": ReviewDecisionEvent.from_event(payload).created_at.isoformat(),
    }


def test_action_must_be_one_of_the_packs_four() -> None:
    assert REVIEW_ACTIONS == (
        "confirm_issue",
        "dismiss_with_reason",
        "request_information",
        "mark_corrected_for_recheck",
    )
    for value in REVIEW_ACTIONS:
        assert ReviewDecisionEvent.model_validate(event(action=value)).action.value == value
    with pytest.raises(ValidationError):
        ReviewDecisionEvent.model_validate(event(action="approve_claim"))


@pytest.mark.parametrize(
    "field", ["claim_id", "rule_id", "action", "actor", "reason", "created_at", "original_status"]
)
def test_every_key_is_required(field: str) -> None:
    payload = event()
    del payload[field]
    with pytest.raises(ValidationError):
        ReviewDecisionEvent.model_validate(payload)


def test_extra_keys_are_refused() -> None:
    """``additionalProperties: false`` in the pack's schema."""
    with pytest.raises(ValidationError):
        ReviewDecisionEvent.model_validate(event(decision_id="ignored"))


@pytest.mark.parametrize("field", ["actor", "reason"])
def test_blank_actor_or_reason_is_refused(field: str) -> None:
    """The pack refuses to record a decision without an actor and a reason."""
    with pytest.raises(ValidationError):
        ReviewDecisionEvent.model_validate(event(**{field: "   "}))
    with pytest.raises(ValidationError):
        ReviewDecisionEvent.model_validate(event(**{field: ""}))


def test_original_status_must_be_a_pack_status() -> None:
    with pytest.raises(ValidationError):
        ReviewDecisionEvent.model_validate(event(original_status="UNKNOWN"))
    for status in Status:
        assert (
            ReviewDecisionEvent.model_validate(event(original_status=status.value)).original_status
            is status
        )


def test_rule_id_must_be_a_documented_rule() -> None:
    with pytest.raises(ValidationError):
        ReviewDecisionEvent.model_validate(event(rule_id="R999"))


def test_timestamps_must_carry_a_timezone() -> None:
    """An offset-less timestamp cannot be rendered to the pack's ISO string honestly."""
    with pytest.raises(ValidationError):
        ReviewDecisionEvent.model_validate(event(created_at="2026-03-21T10:00:00"))
    with pytest.raises(ValidationError):
        RuleRun.model_validate(run(created_at="2026-03-21T10:00:00"))


def test_event_is_immutable() -> None:
    parsed = ReviewDecisionEvent.model_validate(event())
    with pytest.raises(ValidationError):
        parsed.actor = "someone-else"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Decision state machine
# ---------------------------------------------------------------------------


def test_every_action_maps_to_a_review_status() -> None:
    assert REVIEW_STATUSES == (
        "unreviewed",
        "info_requested",
        "confirmed",
        "dismissed",
        "corrected_for_recheck",
    )
    assert (
        next_status(ReviewStatus.UNREVIEWED, ReviewAction.CONFIRM_ISSUE) is ReviewStatus.CONFIRMED
    )
    assert (
        next_status(ReviewStatus.UNREVIEWED, ReviewAction.DISMISS_WITH_REASON)
        is ReviewStatus.DISMISSED
    )
    assert (
        next_status(ReviewStatus.UNREVIEWED, ReviewAction.REQUEST_INFORMATION)
        is ReviewStatus.INFO_REQUESTED
    )
    assert (
        next_status(ReviewStatus.UNREVIEWED, ReviewAction.MARK_CORRECTED_FOR_RECHECK)
        is ReviewStatus.CORRECTED_FOR_RECHECK
    )


def test_an_open_finding_accepts_all_four_actions() -> None:
    for start in (ReviewStatus.UNREVIEWED, ReviewStatus.INFO_REQUESTED):
        assert ALLOWED_TRANSITIONS[start] == frozenset(ReviewAction)


@pytest.mark.parametrize("start", [ReviewStatus.CONFIRMED, ReviewStatus.DISMISSED])
def test_a_decided_finding_can_only_reopen_or_be_corrected(start: ReviewStatus) -> None:
    assert next_status(start, ReviewAction.REQUEST_INFORMATION) is ReviewStatus.INFO_REQUESTED
    assert (
        next_status(start, ReviewAction.MARK_CORRECTED_FOR_RECHECK)
        is ReviewStatus.CORRECTED_FOR_RECHECK
    )
    with pytest.raises(IllegalReviewTransitionError):
        next_status(start, ReviewAction.CONFIRM_ISSUE)
    with pytest.raises(IllegalReviewTransitionError):
        next_status(start, ReviewAction.DISMISS_WITH_REASON)


def test_a_corrected_finding_is_terminal_on_that_version() -> None:
    """After a correction, the open questions belong to the new run's findings."""
    assert ALLOWED_TRANSITIONS[ReviewStatus.CORRECTED_FOR_RECHECK] == frozenset()
    for action in ReviewAction:
        with pytest.raises(IllegalReviewTransitionError):
            next_status(ReviewStatus.CORRECTED_FOR_RECHECK, action)


def test_reopening_after_a_question_returns_to_a_decidable_state() -> None:
    status = next_status(ReviewStatus.UNREVIEWED, ReviewAction.REQUEST_INFORMATION)
    status = next_status(status, ReviewAction.CONFIRM_ISSUE)
    assert status is ReviewStatus.CONFIRMED
    status = next_status(status, ReviewAction.REQUEST_INFORMATION)
    assert is_unresolved(status)


def test_unresolved_means_the_reviewer_still_owes_an_answer() -> None:
    assert is_unresolved(ReviewStatus.UNREVIEWED)
    assert is_unresolved(ReviewStatus.INFO_REQUESTED)
    assert not is_unresolved(ReviewStatus.CONFIRMED)
    assert not is_unresolved(ReviewStatus.DISMISSED)
    assert not is_unresolved(ReviewStatus.CORRECTED_FOR_RECHECK)


def test_review_state_reports_unresolved_consistently() -> None:
    assert ReviewState().unresolved is True
    assert ReviewState(status=ReviewStatus.INFO_REQUESTED).unresolved is True
    assert ReviewState(status=ReviewStatus.CONFIRMED).unresolved is False
    assert (
        ReviewState(status=ReviewStatus.DISMISSED, decision_count=2).model_dump()["unresolved"]
        is False
    )


# ---------------------------------------------------------------------------
# Queue membership
# ---------------------------------------------------------------------------


def test_only_checks_that_need_a_human_enter_the_queue() -> None:
    clean = ResultRecord.model_validate(record(base_claim(), "R001"))
    assert clean.status is Status.PASS
    assert requires_attention(clean) is False

    not_applicable = ResultRecord.model_validate(record(base_claim(), "R008"))
    assert not_applicable.status is Status.NOT_APPLICABLE
    assert requires_attention(not_applicable) is False

    failing = base_claim()
    failing["coverage"]["end_date"] = "2026-03-09"
    flagged = ResultRecord.model_validate(record(failing, "R003"))
    assert flagged.status is Status.FAIL
    assert flagged.requires_human_review is True
    assert requires_attention(flagged) is True


def test_the_fixture_lapse_fails_only_r003() -> None:
    """The integration fixtures depend on this: one failing check, deterministically."""
    lapse = base_claim()
    lapse["coverage"]["end_date"] = "2026-03-09"
    statuses = all_statuses(lapse)
    assert statuses["R003"] == "FAIL"
    assert [
        rule for rule, status in statuses.items() if status not in {"PASS", "NOT_APPLICABLE"}
    ] == ["R003"]


def test_status_summary_always_names_every_pack_status() -> None:
    summary = summarize_statuses([ResultRecord.model_validate(record(base_claim(), "R001"))])
    assert tuple(summary) == tuple(status.value for status in Status)
    assert summary["PASS"] == 1
    assert summary["FAIL"] == 0


# ---------------------------------------------------------------------------
# Run identity
# ---------------------------------------------------------------------------


def test_run_requires_a_sha256_input_hash() -> None:
    assert RuleRun.model_validate(run()).input_hash == HASH
    with pytest.raises(ValidationError):
        RuleRun.model_validate(run(input_hash="not-a-hash"))
    with pytest.raises(ValidationError):
        RuleRun.model_validate(run(input_hash="A" * 64))


def test_run_requires_a_32_hex_trace_id() -> None:
    assert RuleRun.model_validate(run()).trace_id == TRACE
    with pytest.raises(ValidationError):
        RuleRun.model_validate(run(trace_id="too-short"))


@pytest.mark.parametrize(
    "field",
    ["run_id", "claim_id", "rule_version", "model_version", "prompt_version", "initiated_by"],
)
def test_run_text_fields_must_not_be_blank(field: str) -> None:
    with pytest.raises(ValidationError):
        RuleRun.model_validate(run(**{field: "  "}))


def test_run_version_starts_at_one() -> None:
    with pytest.raises(ValidationError):
        RuleRun.model_validate(run(version=0))
    assert RuleRun.model_validate(run(version=3)).version == 3


def test_run_is_a_frozen_record() -> None:
    parsed = RuleRun.model_validate(run())
    with pytest.raises(ValidationError):
        parsed.version = 2  # type: ignore[misc]


def test_the_engine_record_model_still_owns_the_fifteen_keys() -> None:
    """The review surface must not grow its own copy of the result contract."""
    assert len(RESULT_KEYS) == 15
    parsed = ResultRecord.model_validate(record(base_claim(), "R001"))
    assert tuple(parsed.model_dump()) == RESULT_KEYS


def test_timestamps_are_kept_timezone_aware() -> None:
    parsed = RuleRun.model_validate(
        run(created_at=datetime(2026, 3, 21, 10, 0, tzinfo=timezone(timedelta(hours=2))))
    )
    assert parsed.created_at.utcoffset() == timedelta(hours=2)
    assert parsed.created_at.astimezone(UTC).hour == 8
