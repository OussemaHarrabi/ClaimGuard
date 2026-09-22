"""Rule tests R001-R007: one FAIL, one PASS/NOT_APPLICABLE and one abstention each.

Cases are built as small in-memory envelopes (never files) so each rule's
decision boundaries are explicit: docs/04_Rulebook.md:40-94 is the contract.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.edu import base_claim, line, record, status_of

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNABLE_TO_ASSESS"
NOT_APPLICABLE = "NOT_APPLICABLE"


# ---------------------------------------------------------------------------
# R001 — required claim information
# ---------------------------------------------------------------------------


def test_r001_passes_when_required_information_is_present() -> None:
    entry = record(base_claim(), "R001")
    assert entry["status"] == PASS
    assert entry["evidence"][0] == {"path": "/invoice_number", "value": "INV-TEST-0001"}


def test_r001_fails_on_missing_invoice_and_line_amount() -> None:
    claim = base_claim()
    claim["invoice_number"] = None
    claim["lines"][0]["net_amount"] = None
    entry = record(claim, "R001")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1"]
    assert {item["path"] for item in entry["evidence"]} == {
        "/invoice_number",
        "/lines/0/net_amount",
    }


def test_r001_reports_a_blank_string_as_a_known_absence() -> None:
    claim = base_claim()
    claim["diagnosis_code"] = "   "
    assert status_of(claim, "R001") == FAIL


def test_r001_fails_on_a_missing_service_code() -> None:
    """A missing service code is an observed defect under R001, not an abstention."""
    claim = base_claim()
    claim["lines"][0]["service_code"] = None
    entry = record(claim, "R001")
    assert entry["status"] == FAIL
    assert {"path": "/lines/0/service_code", "value": None} in entry["evidence"]


# ---------------------------------------------------------------------------
# R002 — service and submission chronology
# ---------------------------------------------------------------------------


def test_r002_passes_when_service_precedes_submission() -> None:
    assert status_of(base_claim(), "R002") == PASS


def test_r002_passes_on_the_boundary_day() -> None:
    claim = base_claim()
    claim["lines"][0]["service_date"] = claim["submission_date"]
    assert status_of(claim, "R002") == PASS


def test_r002_fails_when_service_follows_submission() -> None:
    claim = base_claim()
    claim["lines"][0]["service_date"] = "2026-03-21"
    entry = record(claim, "R002")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1"]


def test_r002_abstains_on_a_missing_service_date() -> None:
    claim = base_claim()
    claim["lines"][0]["service_date"] = None
    assert status_of(claim, "R002") == UNKNOWN


def test_r002_fails_when_another_line_proves_a_violation() -> None:
    """A proven violation outranks a missing input (docs/04_Rulebook.md:9)."""
    claim = base_claim()
    claim["lines"] = [
        line(service_date=None),
        line(
            line_id="L2",
            service_date="2026-04-01",
            service_code="SVC-LAB",
            unit_price=120,
            net_amount=120,
        ),
    ]
    entry = record(claim, "R002")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L2"]


# ---------------------------------------------------------------------------
# R003 — coverage active on the service date
# ---------------------------------------------------------------------------


def test_r003_passes_inside_the_coverage_period() -> None:
    assert status_of(base_claim(), "R003") == PASS


def test_r003_passes_inclusively_on_the_period_boundaries() -> None:
    claim = base_claim()
    claim["coverage"]["start_date"] = "2026-03-10"
    claim["coverage"]["end_date"] = "2026-03-10"
    assert status_of(claim, "R003") == PASS


def test_r003_fails_outside_the_coverage_period() -> None:
    claim = base_claim()
    claim["coverage"]["end_date"] = "2026-03-09"
    entry = record(claim, "R003")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1"]


def test_r003_fails_on_a_non_active_coverage_status() -> None:
    claim = base_claim()
    claim["coverage"]["status"] = "cancelled"
    assert status_of(claim, "R003") == FAIL


def test_r003_abstains_when_the_coverage_period_is_incomplete() -> None:
    claim = base_claim()
    claim["coverage"]["end_date"] = None
    assert status_of(claim, "R003") == UNKNOWN


# ---------------------------------------------------------------------------
# R004 — member and beneficiary consistency
# ---------------------------------------------------------------------------


def test_r004_passes_on_matching_identifiers() -> None:
    assert status_of(base_claim(), "R004") == PASS


def test_r004_fails_on_a_member_mismatch() -> None:
    claim = base_claim()
    claim["coverage"]["member_id"] = "MEM-OTHER"
    entry = record(claim, "R004")
    assert entry["status"] == FAIL
    assert {"path": "/coverage/member_id", "value": "MEM-OTHER"} in entry["evidence"]


def test_r004_is_case_sensitive() -> None:
    claim = base_claim()
    claim["patient_id"] = "pat-test"
    assert status_of(claim, "R004") == FAIL


def test_r004_abstains_when_a_comparison_value_is_missing() -> None:
    claim = base_claim()
    claim["member_id"] = None
    assert status_of(claim, "R004") == UNKNOWN


# ---------------------------------------------------------------------------
# R005 — provider in the supplied network
# ---------------------------------------------------------------------------


def test_r005_passes_for_a_listed_provider() -> None:
    assert status_of(base_claim(), "R005") == PASS


def test_r005_fails_for_an_unlisted_provider() -> None:
    claim = base_claim()
    claim["provider_id"] = "EDU-PROV-OUT"
    entry = record(claim, "R005")
    assert entry["status"] == FAIL
    assert entry["evidence"] == [
        {"path": "/provider_id", "value": "EDU-PROV-OUT"},
        {"path": "/policy_id", "value": "EDU-BASIC"},
    ]


def test_r005_abstains_without_a_matching_policy() -> None:
    claim = base_claim()
    claim["policy_id"] = "EDU-NO-POLICY"
    entry = record(claim, "R005")
    assert entry["status"] == UNKNOWN
    assert "No policy" in entry["explanation"]


# ---------------------------------------------------------------------------
# R006 — possible duplicate service lines
# ---------------------------------------------------------------------------


def test_r006_passes_without_repeated_lines() -> None:
    assert status_of(base_claim(), "R006") == PASS


def test_r006_passes_for_repeats_with_different_modifiers() -> None:
    """Different modifiers or dates are not duplicates (docs/04_Rulebook.md:82)."""
    claim = base_claim()
    claim["lines"] = [
        line(),
        line(line_id="L2", modifier="EDU-SEPARATE"),
    ]
    assert status_of(claim, "R006") == PASS


def test_r006_fails_on_a_repeated_service_date_and_modifier() -> None:
    claim = base_claim()
    claim["lines"] = [line(), line(line_id="L2")]
    entry = record(claim, "R006")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1", "L2"]
    assert entry["evidence"][0] == {"path": "/lines/0/service_code", "value": "SVC-CONSULT"}


def test_r006_treats_null_and_empty_modifier_as_equal() -> None:
    claim = base_claim()
    claim["lines"] = [line(modifier=None), line(line_id="L2", modifier="")]
    assert status_of(claim, "R006") == FAIL


def test_r006_abstains_when_a_date_is_missing() -> None:
    claim = base_claim()
    claim["lines"][0]["service_date"] = None
    assert status_of(claim, "R006") == UNKNOWN


def test_r006_fails_when_a_complete_pair_proves_a_duplicate() -> None:
    claim = base_claim()
    claim["lines"] = [
        line(service_date=None),
        line(line_id="L2"),
        line(line_id="L3"),
    ]
    entry = record(claim, "R006")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L2", "L3"]


# ---------------------------------------------------------------------------
# R007 — line arithmetic
# ---------------------------------------------------------------------------


def test_r007_passes_when_the_line_amount_matches() -> None:
    assert status_of(base_claim(), "R007") == PASS


def test_r007_passes_within_the_one_cent_tolerance() -> None:
    claim = base_claim()
    claim["lines"][0]["net_amount"] = 190.01
    assert status_of(claim, "R007") == PASS


def test_r007_fails_when_the_line_amount_differs() -> None:
    claim = base_claim()
    claim["lines"][0]["unit_price"] = 191
    entry = record(claim, "R007")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1"]


def test_r007_rounds_half_up() -> None:
    """quantity 3 x 0.335 = 1.005 rounds to 1.01, never 1.00 (binary floats)."""
    claim = base_claim()
    claim["lines"][0]["quantity"] = 3
    claim["lines"][0]["unit_price"] = 0.335
    claim["lines"][0]["net_amount"] = 1.01
    assert status_of(claim, "R007") == PASS


def test_r007_abstains_when_an_arithmetic_input_is_missing() -> None:
    claim = base_claim()
    claim["lines"][0]["unit_price"] = None
    assert status_of(claim, "R007") == UNKNOWN


def test_r007_fails_when_another_line_differs() -> None:
    claim = base_claim()
    claim["lines"] = [
        line(unit_price=None),
        line(line_id="L2", quantity=2, unit_price=120, net_amount=250),
    ]
    entry = record(claim, "R007")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L2"]


@pytest.mark.parametrize(
    ("amount", "expected"), [(189.99, PASS), (190.01, PASS), (189.98, FAIL), (190.02, FAIL)]
)
def test_r007_one_cent_tolerance_boundary(amount: Any, expected: str) -> None:
    claim = base_claim()
    claim["lines"][0]["net_amount"] = amount
    assert status_of(claim, "R007") == expected


def test_r007_does_not_judge_negative_amounts_arithmetically() -> None:
    """Negative inputs are evaluated arithmetically here; R013 judges validity."""
    claim = base_claim()
    claim["lines"][0]["quantity"] = -1
    claim["lines"][0]["net_amount"] = -190
    assert status_of(claim, "R007") == PASS
    assert status_of(claim, "R013") == FAIL
