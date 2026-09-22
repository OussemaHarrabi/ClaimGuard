"""Rulebook edge cases the public gold splits cannot discriminate (R001-R015).

Every test states the clause it pins, with file and line:

* ``docs/04_Rulebook.md``          — shared conventions (lines 7-17) and per-rule prose
* ``rules/rules.json``             — the machine-readable counterpart (``logic`` field)
* ``docs/03_Data_Dictionary.md``   — value semantics of the transport contract
* ``src/engine_core.py``           — the mentor's own reference core where it arbitrates
* ``docs/13_Worked_Examples.md``   — the mentor's worked answers

Two deliberate policies:

* The catalogue parameters this suite leans on (policy limits, windows, required
  services) are asserted up front by ``test_pack_parameters_*``; a drifted
  vendored catalogue can therefore not make these edges pass vacuously.
* Where the rulebook is genuinely ambiguous and no gold label can arbitrate, the
  test asserts the engine's *current* behaviour and is marked ``xfail(strict=False)``
  with "rulebook ambiguous; gold cannot arbitrate — flagged for the mentor".
  Those cases pin an implementation choice, never a rulebook requirement.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from claimguard.edu.envelope import money, to_decimal

from tests.edu import (
    all_statuses,
    attachment,
    authorization,
    base_claim,
    imaging_claim,
    line,
    record,
    rules_context,
    status_of,
)

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNABLE_TO_ASSESS"
NOT_APPLICABLE = "NOT_APPLICABLE"


# ---------------------------------------------------------------------------
# Preconditions — the catalogue parameters these edges depend on
# ---------------------------------------------------------------------------


def test_pack_parameters_the_edge_cases_depend_on() -> None:
    """Pins the policy/service parameters the edge cases are written against.

    docs/04_Rulebook.md:19-38 (policy profiles and the service table): the
    submission window is 30 days for EDU-BASIC and 60 for EDU-PLUS, SVC-IMAGE
    and SVC-THERAPY require an authorization, SVC-IMAGE requires an
    ``imaging-report``, and SVC-CONSULT/SVC-LAB cap at 350/260 SAR and 1/3 per
    line. A changed catalogue would silently weaken the tests below.
    """
    ctx = rules_context()
    basic = ctx.policy("EDU-BASIC")
    plus = ctx.policy("EDU-PLUS")
    assert basic is not None
    assert plus is not None
    assert (basic.submission_window_days, plus.submission_window_days) == (30, 60)
    assert ctx.knows_service("SVC-UNLISTED") is False
    for code in ("SVC-CONSULT", "SVC-LAB", "SVC-IMAGE", "SVC-THERAPY", "SVC-DENTAL", "SVC-PHARM"):
        assert ctx.knows_service(code), code
    assert basic.auth_required("SVC-IMAGE") and basic.auth_required("SVC-THERAPY")
    assert not basic.auth_required("SVC-CONSULT")
    assert basic.required_document("SVC-IMAGE") == "imaging-report"
    assert basic.max_quantity_for("SVC-IMAGE") == 1
    assert basic.max_quantity_for("SVC-LAB") == 3
    assert basic.max_price_for("SVC-CONSULT") == 350


# ---------------------------------------------------------------------------
# R001 — whitespace-only strings and no silent repair
# ---------------------------------------------------------------------------


def test_r001_treats_a_whitespace_only_string_as_a_known_absence() -> None:
    """R001: required values "must be present and non-null; strings must not be
    empty" and "A known absence is FAIL, not UNABLE_TO_ASSESS"
    (docs/04_Rulebook.md:42; rules/rules.json:6). The pack's own reference
    validator defines the absence as ``not v.strip()`` (src/engine_core.py:20),
    so a blank string is a defect — while the observed value is reported
    VERBATIM, because "Do not silently trim or repair source data before
    checking" (docs/04_Rulebook.md:14).
    """
    claim = base_claim()
    claim["invoice_number"] = "   "
    claim["diagnosis_code"] = "\t\n"
    claim["lines"][0]["service_date"] = " "
    entry = record(claim, "R001")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1"]
    assert {"path": "/invoice_number", "value": "   "} in entry["evidence"]
    assert {"path": "/diagnosis_code", "value": "\t\n"} in entry["evidence"]
    assert {"path": "/lines/0/service_date", "value": " "} in entry["evidence"]


def test_r015_does_not_trim_a_padded_currency_before_comparing() -> None:
    """docs/04_Rulebook.md:14 ("Do not silently trim or repair source data before
    checking") applied to R015, which requires ``currency`` to equal
    ``policy.currency`` (docs/04_Rulebook.md:154; rules/rules.json:132): a padded
    "SAR " is a FAIL, never a repaired PASS.
    """
    claim = base_claim()
    claim["currency"] = "SAR "
    assert status_of(claim, "R015") == FAIL


# ---------------------------------------------------------------------------
# R002 / R014 — negative lag, equal dates, and the latest-date reduction
# ---------------------------------------------------------------------------


def test_r002_fails_and_r014_is_not_applicable_on_a_negative_lag() -> None:
    """R014: "Negative lag is NOT_APPLICABLE here and is handled by R002"
    (docs/04_Rulebook.md:146; rules/rules.json:123) — the same chronology defect
    is scored by exactly one rule. R002: "Every service_date must be on or before
    submission_date" (docs/04_Rulebook.md:50).
    """
    claim = base_claim()
    claim["submission_date"] = "2026-03-01"
    assert status_of(claim, "R002") == FAIL
    assert status_of(claim, "R014") == NOT_APPLICABLE


def test_r002_and_r014_pass_on_equal_dates() -> None:
    """R002 "Equality passes" (docs/04_Rulebook.md:50) and R014 "Equality passes"
    (docs/04_Rulebook.md:146; rules/rules.json:123): a service on the submission
    day is a zero-day lag, inside every window.
    """
    claim = base_claim()
    claim["lines"][0]["service_date"] = "2026-03-20"
    claim["submission_date"] = "2026-03-20"
    assert status_of(claim, "R002") == PASS
    assert status_of(claim, "R014") == PASS


def _two_dated_claim() -> dict[str, Any]:
    """Two consult lines on 2026-02-01 and 2026-03-10 (earliest/latest probe)."""
    claim = base_claim()
    claim["lines"] = [
        line(service_date="2026-02-01"),
        line(
            line_id="L2",
            service_code="SVC-LAB",
            service_date="2026-03-10",
            quantity=1,
            unit_price=100,
            net_amount=100,
        ),
    ]
    claim["total_amount"] = 290
    return claim


def test_r014_measures_the_window_from_the_latest_service_date() -> None:
    """R014: "submission_date minus the latest service_date must be <=
    policy.submission_window_days" (docs/04_Rulebook.md:146; rules/rules.json:123).

    With service dates 2026-02-01 and 2026-03-10, a submission on 2026-03-20 is
    10 days after the LATEST date (PASS) but 47 days after the earliest (FAIL),
    and 2026-04-09 is the inclusive 30-day boundary of EDU-BASIC. Every public
    claim has exactly one service date, so only this reduction distinguishes the
    two readings.
    """
    claim = _two_dated_claim()
    claim["submission_date"] = "2026-03-20"
    assert status_of(claim, "R014") == PASS
    claim["submission_date"] = "2026-04-09"
    assert status_of(claim, "R014") == PASS
    claim["submission_date"] = "2026-04-10"
    assert status_of(claim, "R014") == FAIL


def test_r014_reduction_stays_negative_when_another_line_is_in_the_future() -> None:
    """R014 reduces over the LATEST service date (docs/04_Rulebook.md:146): with
    one line after the submission the reduction is negative, so R014 abstains as
    NOT_APPLICABLE while R002 proves the violation (docs/04_Rulebook.md:50). A
    minimum/first-date reduction would instead see a positive 19-day lag and PASS.
    """
    claim = _two_dated_claim()
    claim["lines"][0]["service_date"] = "2026-03-01"
    claim["lines"][1]["service_date"] = "2026-03-25"
    claim["submission_date"] = "2026-03-20"
    assert status_of(claim, "R002") == FAIL
    assert status_of(claim, "R014") == NOT_APPLICABLE


# ---------------------------------------------------------------------------
# R003 — inclusive coverage boundaries
# ---------------------------------------------------------------------------


def test_r003_includes_both_coverage_boundaries_exactly() -> None:
    """R003: "every service_date must be within coverage.start_date and
    coverage.end_date, both inclusive" (docs/04_Rulebook.md:58;
    rules/rules.json:24; docs/04_Rulebook.md:13 "Boundaries are inclusive").
    """
    claim = base_claim()
    claim["coverage"]["start_date"] = "2026-03-10"
    claim["coverage"]["end_date"] = "2026-03-10"
    assert status_of(claim, "R003") == PASS
    claim = base_claim()
    claim["coverage"]["start_date"] = "2026-01-01"
    claim["coverage"]["end_date"] = "2026-03-10"
    assert status_of(claim, "R003") == PASS


def test_r003_fails_one_day_outside_either_boundary() -> None:
    """R003: a service date one day before the start or one day after the end is
    a known violation -> "A known non-active status or out-of-period date is
    FAIL" (docs/04_Rulebook.md:58; rules/rules.json:25).
    """
    claim = base_claim()
    claim["coverage"]["start_date"] = "2026-03-11"
    entry = record(claim, "R003")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1"]
    claim = base_claim()
    claim["coverage"]["end_date"] = "2026-03-09"
    assert status_of(claim, "R003") == FAIL


# ---------------------------------------------------------------------------
# R006 — the duplicate key and null-modifier normalisation
# ---------------------------------------------------------------------------


def test_r006_normalises_a_null_modifier_to_empty() -> None:
    """R006: "Flag repeated (service_code, service_date, modifier) within one
    claim. Normalize null modifier to an empty string." (docs/04_Rulebook.md:82;
    rules/rules.json:51; docs/03_Data_Dictionary.md:39 "Null modifier normalizes
    to empty only for R006"). Two otherwise identical lines with null modifiers
    are therefore duplicates.
    """
    claim = base_claim()
    claim["lines"] = [line(modifier=None), line(line_id="L2", modifier=None)]
    entry = record(claim, "R006")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1", "L2"]
    assert {"/lines/0/modifier", "/lines/1/modifier"} <= {
        item["path"] for item in entry["evidence"]
    }


def test_r006_flags_two_lines_carrying_the_same_non_null_modifier() -> None:
    """R006 keys on the triple (service_code, service_date, modifier)
    (docs/04_Rulebook.md:82): equal non-null modifiers on the same code and date
    are duplicates. No public split repeats a non-null modifier.
    """
    claim = base_claim()
    claim["lines"] = [line(modifier="EDU-SAME"), line(line_id="L2", modifier="EDU-SAME")]
    assert status_of(claim, "R006") == FAIL


def test_r006_does_not_flag_different_modifiers_on_the_same_service_date() -> None:
    """R006: "Different modifiers or dates are not duplicates under this rule."
    (docs/04_Rulebook.md:82; rules/rules.json:51) — including a null modifier
    against a populated one, since only ``null`` normalises to ``""``.
    """
    claim = base_claim()
    claim["lines"] = [line(modifier=None), line(line_id="L2", modifier="EDU-SEPARATE")]
    assert status_of(claim, "R006") == PASS
    claim = base_claim()
    claim["lines"] = [line(modifier="EDU-M1"), line(line_id="L2", modifier="EDU-M2")]
    assert status_of(claim, "R006") == PASS


# ---------------------------------------------------------------------------
# R007 — cent-level arithmetic, ROUND_HALF_UP and decimal arithmetic
# ---------------------------------------------------------------------------


def test_r007_applies_the_inclusive_one_cent_tolerance_at_cent_precision() -> None:
    """R007: "net_amount must equal quantity multiplied by unit_price ... A
    difference of at most 0.01 SAR passes" (docs/04_Rulebook.md:90;
    rules/rules.json:60) with the inclusive tolerance of docs/04_Rulebook.md:13.
    No public split contains a cent, so this is the only probe of the boundary.
    """
    claim = base_claim()
    claim["lines"][0].update(quantity=1, unit_price=190.25, net_amount=190.26)
    assert status_of(claim, "R007") == PASS
    claim["lines"][0]["net_amount"] = 190.27
    entry = record(claim, "R007")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1"]


def test_r007_rounds_the_product_half_up_to_cents() -> None:
    """R007: "rounded to 2 decimal places using decimal ROUND_HALF_UP"
    (docs/04_Rulebook.md:90; rules/rules.json:60). A half-up/half-even difference
    is exactly one cent, i.e. inside the 0.01 tolerance, so the rule level hides
    it: the arithmetic primitive is pinned directly at the half-way values.
    """
    assert money(Decimal("1.005")) == Decimal("1.01")
    assert money(Decimal("2.675")) == Decimal("2.68")
    assert money(Decimal("0.005")) == Decimal("0.01")
    assert money(Decimal("1.004")) == Decimal("1.00")
    claim = base_claim()
    claim["lines"][0].update(quantity=3, unit_price=0.335, net_amount=1.01)
    assert status_of(claim, "R007") == PASS


def test_r007_uses_decimal_arithmetic_not_binary_floats() -> None:
    """R007 arithmetic is decimal: "Use decimal arithmetic and ROUND_HALF_UP"
    (docs/04_Rulebook.md:13) and "Prices use decimal arithmetic; do not round with
    binary floating-point comparisons" (docs/03_Data_Dictionary.md:39).
    """
    assert to_decimal(0.1) + to_decimal(0.2) == Decimal("0.3")
    assert 0.1 + 0.2 != 0.3  # the binary-float behaviour this guards against
    claim = base_claim()
    claim["lines"][0].update(quantity=3, unit_price=0.1, net_amount=0.3)
    assert status_of(claim, "R007") == PASS


# ---------------------------------------------------------------------------
# R009 — cross-line quantity aggregation and the complete inventory
# ---------------------------------------------------------------------------


def _shared_authorization_claim(line_count: int, max_quantity: Any) -> dict[str, Any]:
    """``line_count`` SVC-IMAGE lines, each quantity 1, sharing AUTH-TEST-1."""
    claim = imaging_claim()
    claim["lines"] = [
        line(
            line_id=f"L{index}",
            service_code="SVC-IMAGE",
            unit_price=1500,
            net_amount=1500,
            authorization_id="AUTH-TEST-1",
        )
        for index in range(1, line_count + 1)
    ]
    claim["total_amount"] = 1500 * line_count
    claim["authorizations"] = [authorization(max_quantity=max_quantity)]
    return claim


def test_r009_aggregates_quantity_across_lines_sharing_one_authorization() -> None:
    """R009: "aggregate quantity across lines sharing that authorization_id <=
    max_quantity" (docs/04_Rulebook.md:106; rules/rules.json:78;
    docs/03_Data_Dictionary.md:41 "aggregate all lines sharing that reference").

    Each line is within ``max_quantity=1`` on its own, so only the SUM proves the
    violation; the public splits only ever show a single line exceeding the limit.
    """
    claim = _shared_authorization_claim(line_count=2, max_quantity=1)
    entry = record(claim, "R009")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1", "L2"]


def test_r009_passes_when_the_aggregate_equals_max_quantity() -> None:
    """R009 bounds the aggregate with "<=" (docs/04_Rulebook.md:106;
    rules/rules.json:78): three quantity-1 lines against ``max_quantity=3`` are at
    the limit, not over it.
    """
    claim = _shared_authorization_claim(line_count=3, max_quantity=3)
    assert status_of(claim, "R009") == PASS


def test_r009_does_not_aggregate_lines_with_different_authorization_ids() -> None:
    """R009 aggregates "across lines sharing that authorization_id"
    (docs/04_Rulebook.md:106): two quantity-1 lines under two different
    references are bounded separately, so neither exceeds its ``max_quantity=1``.
    """
    claim = imaging_claim()
    claim["lines"].append(
        line(
            line_id="L2",
            service_code="SVC-IMAGE",
            unit_price=1500,
            net_amount=1500,
            authorization_id="AUTH-TEST-2",
        )
    )
    claim["total_amount"] = 3000
    claim["authorizations"] = [
        authorization(authorization_id="AUTH-TEST-1", max_quantity=1),
        authorization(authorization_id="AUTH-TEST-2", max_quantity=1),
    ]
    assert status_of(claim, "R009") == PASS


def test_r009_fails_when_a_referenced_id_is_absent_from_a_complete_inventory() -> None:
    """R009: "A referenced ID absent from the supplied complete list or a known
    mismatch fails" (docs/04_Rulebook.md:106; rules/rules.json:78), and the
    authorizations array is a KNOWN inventory for the snapshot
    (docs/04_Rulebook.md:12). A different, perfectly valid authorization
    referenced by another line must not be borrowed as a fallback.
    """
    claim = base_claim()
    claim["lines"] = [
        line(
            service_code="SVC-IMAGE",
            unit_price=1500,
            net_amount=1500,
            authorization_id="AUTH-GONE",
        ),
        line(
            line_id="L2",
            service_code="SVC-THERAPY",
            unit_price=450,
            net_amount=450,
            authorization_id="AUTH-OK",
        ),
    ]
    claim["total_amount"] = 1950
    claim["authorizations"] = [
        authorization(authorization_id="AUTH-OK", service_code="SVC-THERAPY", max_quantity=1)
    ]
    entry = record(claim, "R009")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1"]
    assert {"path": "/lines/0/authorization_id", "value": "AUTH-GONE"} in entry["evidence"]
    assert status_of(claim, "R008") == PASS  # both references are present


# ---------------------------------------------------------------------------
# R010 — draft vs final documents and the patient match
# ---------------------------------------------------------------------------


def test_r010_requires_a_final_matching_document() -> None:
    """R010: "If any matching attachment has document_status final, PASS for that
    line; if matching attachments exist but all are draft/unknown,
    UNABLE_TO_ASSESS." (docs/04_Rulebook.md:114; rules/rules.json:86;
    docs/13_Worked_Examples.md:53-55 for the draft case).
    """
    claim = imaging_claim()
    assert status_of(claim, "R010") == PASS
    claim["attachments"] = [attachment(document_status="draft")]
    assert status_of(claim, "R010") == UNKNOWN
    claim["attachments"] = [attachment(document_status="unknown")]
    assert status_of(claim, "R010") == UNKNOWN
    claim["attachments"] = [
        attachment(attachment_id="DOC-1", document_status="draft"),
        attachment(attachment_id="DOC-2", document_status="final"),
    ]
    assert status_of(claim, "R010") == PASS


def test_r010_does_not_count_a_document_for_another_patient() -> None:
    """R010: "At least one attachment must match type, patient_id, service_code
    and service_date" (docs/04_Rulebook.md:114; rules/rules.json:86). A final
    document for a DIFFERENT patient is not a match, so it neither satisfies the
    requirement nor turns a correct-but-draft document into a PASS.
    """
    claim = imaging_claim()
    claim["attachments"] = [attachment(patient_id="PAT-OTHER", document_status="final")]
    entry = record(claim, "R010")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1"]
    assert "/attachments" in {item["path"] for item in entry["evidence"]}
    claim["attachments"].append(attachment(attachment_id="DOC-2", document_status="draft"))
    assert status_of(claim, "R010") == UNKNOWN
    claim["attachments"].append(attachment(attachment_id="DOC-3", document_status="final"))
    assert status_of(claim, "R010") == PASS


# ---------------------------------------------------------------------------
# Precedence — a proven violation outranks an abstention (docs/04_Rulebook.md:10)
# ---------------------------------------------------------------------------


def test_r011_fail_outranks_a_missing_service_code_on_another_line() -> None:
    """docs/04_Rulebook.md:10 "a proven violation gives FAIL; otherwise missing
    necessary evidence gives UNABLE_TO_ASSESS"; R011 "An unknown code fails; a
    missing code leaves UNABLE_TO_ASSESS" (docs/04_Rulebook.md:122;
    rules/rules.json:96). The unknown code wins the status, and only the failing
    line is flagged.
    """
    claim = base_claim()
    claim["lines"] = [
        line(service_code=None),
        line(line_id="L2", service_code="SVC-UNLISTED", unit_price=10, net_amount=10),
    ]
    entry = record(claim, "R011")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L2"]


def test_r013_fail_outranks_an_unknown_service_code_on_another_line() -> None:
    """R013: "Missing values, unknown code or unavailable policy leave
    UNABLE_TO_ASSESS unless another line proves a violation"
    (docs/04_Rulebook.md:140; rules/rules.json:114), with the precedence of
    docs/04_Rulebook.md:10.
    """
    claim = base_claim()
    claim["lines"] = [
        line(service_code="SVC-UNLISTED", unit_price=10, net_amount=10),
        line(line_id="L2", service_code="SVC-CONSULT", quantity=1, unit_price=400, net_amount=400),
    ]
    claim["total_amount"] = 410
    entry = record(claim, "R013")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L2"]


def test_r008_fail_outranks_an_unknown_service_code_on_another_line() -> None:
    """R008: "Unknown service codes or an unavailable policy leave
    UNABLE_TO_ASSESS unless another required line fails"
    (docs/04_Rulebook.md:98; rules/rules.json:69).
    """
    claim = base_claim()
    claim["lines"] = [
        line(service_code="SVC-UNLISTED", unit_price=10, net_amount=10),
        line(
            line_id="L2",
            service_code="SVC-IMAGE",
            unit_price=1500,
            net_amount=1500,
            authorization_id=None,
        ),
    ]
    claim["total_amount"] = 1510
    entry = record(claim, "R008")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L2"]


def test_r009_fail_outranks_an_unknown_service_code_on_another_line() -> None:
    """R009 corroborates R008 ("This checks reference presence only; R009 checks
    the record", docs/04_Rulebook.md:100): a referenced id absent from the empty
    inventory fails (docs/04_Rulebook.md:106) even though another line's service
    code is unknown.
    """
    claim = base_claim()
    claim["lines"] = [
        line(service_code="SVC-UNLISTED", unit_price=10, net_amount=10),
        line(
            line_id="L2",
            service_code="SVC-IMAGE",
            unit_price=1500,
            net_amount=1500,
            authorization_id="AUTH-MISSING",
        ),
    ]
    claim["total_amount"] = 1510
    claim["authorizations"] = []
    entry = record(claim, "R009")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L2"]


def test_r010_fail_outranks_an_unknown_service_code_on_another_line() -> None:
    """R010: "Absent or mismatched required documentation fails"
    (docs/04_Rulebook.md:114) outranks the unknown-service abstention of
    docs/04_Rulebook.md:116, following docs/04_Rulebook.md:10.
    """
    claim = base_claim()
    claim["lines"] = [
        line(service_code="SVC-UNLISTED", unit_price=10, net_amount=10),
        line(
            line_id="L2",
            service_code="SVC-IMAGE",
            unit_price=1500,
            net_amount=1500,
            authorization_id="AUTH-1",
        ),
    ]
    claim["total_amount"] = 1510
    claim["attachments"] = []
    entry = record(claim, "R010")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L2"]


def test_r003_fail_preserves_concurrent_uncertainty_in_the_explanation() -> None:
    """docs/04_Rulebook.md:10 ends the precedence convention with "Preserve
    uncertainty in the explanation even when a different line proves a failure",
    and the mentor's own reference R003 appends "Additional unknown inputs: ..."
    to a failure message (pack src/engine_core.py, R003). Here one line proves a
    coverage violation while the coverage period itself is unknown, so the
    explanation must carry BOTH facts: the reviewer must be able to tell a proven
    failure from an incomplete check.
    """
    claim = base_claim()
    claim["coverage"]["start_date"] = None
    claim["coverage"]["end_date"] = "2026-03-09"
    entry = record(claim, "R003")
    assert entry["status"] == FAIL
    assert entry["explanation"] == (
        "service outside coverage period; Additional unknown inputs: coverage period"
    )


# ---------------------------------------------------------------------------
# Unknown service code — abstention, never NOT_APPLICABLE
# ---------------------------------------------------------------------------


def test_unknown_service_code_abstains_rather_than_being_not_applicable() -> None:
    """docs/04_Rulebook.md:98 (R008), :106 (R009), :116 (R010) and :140 (R013):
    an unknown service code leaves these rules at UNABLE_TO_ASSESS because the
    requirement it might carry is unknown — it is not a proved absence of a
    requirement, so NOT_APPLICABLE would be wrong.
    """
    claim = base_claim()
    claim["lines"] = [line(service_code="SVC-UNLISTED", unit_price=10, net_amount=10)]
    statuses = all_statuses(claim)
    for rule_id in ("R008", "R009", "R010", "R013"):
        assert statuses[rule_id] == UNKNOWN, rule_id
    assert statuses["R011"] == FAIL  # the code is genuinely absent from the catalogue
    entry = record(claim, "R008")
    assert {"path": "/lines/0/service_code", "value": "SVC-UNLISTED"} in entry["evidence"]


def test_unknown_service_code_abstains_even_beside_a_catalogued_line() -> None:
    """Same clauses: an unknown line could require an authorization or a document,
    so a well-known SVC-CONSULT line elsewhere does not let R008/R009/R010 answer
    NOT_APPLICABLE, and R013 abstains per line (docs/04_Rulebook.md:140).
    """
    claim = base_claim()
    claim["lines"].append(
        line(line_id="L2", service_code="SVC-UNLISTED", unit_price=10, net_amount=10)
    )
    claim["total_amount"] = 200
    statuses = all_statuses(claim)
    for rule_id in ("R008", "R009", "R010", "R013"):
        assert statuses[rule_id] == UNKNOWN, rule_id


# ---------------------------------------------------------------------------
# Unknown policy_id — abstention without an invented fallback
# ---------------------------------------------------------------------------


def test_unknown_policy_id_abstains_for_every_policy_dependent_rule() -> None:
    """docs/04_Rulebook.md:12 "An unrecognized policy_id means no matching policy
    was supplied, not proof of non-coverage"; per rule an unavailable policy is
    UNABLE_TO_ASSESS (R005 :74, R008 :98, R009 :106, R010 :116, R013 :140,
    R014 :148, R015 :156 — docs/13_Worked_Examples.md:78-84 lists exactly these
    seven rules). No fallback profile may be invented: R015 must not compare
    against a default SAR, R014 must not apply a default window.
    """
    claim = base_claim()
    claim["policy_id"] = "EDU-NO-POLICY"
    statuses = all_statuses(claim)
    for rule_id in ("R005", "R008", "R009", "R010", "R013", "R014", "R015"):
        assert statuses[rule_id] == UNKNOWN, rule_id
        entry = record(claim, rule_id)
        assert entry["explanation"] == "No policy is supplied for this policy_id."
        assert {"path": "/policy_id", "value": "EDU-NO-POLICY"} in entry["evidence"]
    for rule_id in ("R001", "R002", "R003", "R004", "R006", "R007", "R011", "R012"):
        assert statuses[rule_id] == PASS, rule_id


# ---------------------------------------------------------------------------
# R012 — total vs sum, tolerance and ROUND_HALF_UP
# ---------------------------------------------------------------------------


def test_r012_applies_the_inclusive_one_cent_tolerance() -> None:
    """R012: "Absolute difference <= 0.01 SAR passes" (docs/04_Rulebook.md:130;
    rules/rules.json:105) with the inclusive tolerance of docs/04_Rulebook.md:13:
    190.01 passes, 190.02 fails.
    """
    claim = base_claim()
    claim["total_amount"] = 190.01
    assert status_of(claim, "R012") == PASS
    claim["total_amount"] = 190.02
    entry = record(claim, "R012")
    assert entry["status"] == FAIL
    assert entry["evidence"][0] == {"path": "/total_amount", "value": 190.02}


def test_r012_compares_the_total_with_the_submitted_line_sum() -> None:
    """R012: "total_amount must equal the sum of the submitted line net_amount
    values" (docs/04_Rulebook.md:130; rules/rules.json:105) — the submitted
    amounts, not the arithmetic-correct ones (which R007 checks independently).
    """
    claim = base_claim()
    claim["lines"] = [
        line(unit_price=190, net_amount=190),
        line(
            line_id="L2",
            service_code="SVC-LAB",
            unit_price=120.5,
            net_amount=120.5,
        ),
    ]
    claim["total_amount"] = 310.51
    assert status_of(claim, "R012") == PASS
    claim["total_amount"] = 310.52
    assert status_of(claim, "R012") == FAIL


def test_r012_rounds_each_line_amount_half_up_before_summing() -> None:
    """R012 total is compared at cent precision "rounded to 2 decimals with
    ROUND_HALF_UP" (docs/04_Rulebook.md:130; rules/rules.json:105) inside a 0.01
    tolerance (docs/04_Rulebook.md:13). Three 0.005 lines canonicalise to 0.01
    each under ROUND_HALF_UP, so their sum is 0.03; rounding half-even would give
    0.00 and the submitted 0.03 would be 0.03 away — a plain FAIL.
    """
    claim = base_claim()
    claim["lines"] = [
        line(line_id=f"L{index}", quantity=1, unit_price=0.005, net_amount=0.005)
        for index in (1, 2, 3)
    ]
    claim["total_amount"] = 0.03
    entry = record(claim, "R012")
    assert entry["status"] == PASS
    assert entry["evidence"][0] == {"path": "/total_amount", "value": 0.03}
    claim["total_amount"] = 0.05
    assert status_of(claim, "R012") == FAIL


# Resolution [INFERENCE]: the mentor's own money() helper quantises each monetary
# value individually (pack src/engine_core.py:19), so "round per line, then sum" is
# the convention the unseen full reference most likely follows. No public split
# carries a sub-cent net_amount, so gold cannot arbitrate either way.
def test_r012_quantisation_order_is_round_each_line_then_sum() -> None:
    """R012 says "the sum of the submitted line net_amount values, rounded to 2
    decimals with ROUND_HALF_UP" (docs/04_Rulebook.md:130), which can be read as
    round-per-line-then-sum (the engine's behaviour) or round-the-sum. For
    sub-cent inputs the two differ by whole cents: six 0.005 lines sum to 0.030,
    i.e. 0.06 when each line rounds first and 0.03 when the sum does. The public
    splits contain no sub-cent net_amount, so no gold can arbitrate; this pins the
    engine's reading.
    """
    claim = base_claim()
    claim["lines"] = [
        line(line_id=f"L{index}", quantity=1, unit_price=0.005, net_amount=0.005)
        for index in range(1, 7)
    ]
    claim["total_amount"] = 0.06
    assert status_of(claim, "R012") == PASS
    assert money(Decimal("0.030")) == Decimal("0.03")  # what round-the-sum would yield


# ---------------------------------------------------------------------------
# R013 — positive-integer quantity and price limits
# ---------------------------------------------------------------------------


def test_r013_rejects_fractional_zero_and_negative_quantities() -> None:
    """R013: "Every quantity must be a positive integer ... A known violation
    fails" (docs/04_Rulebook.md:138-140; rules/rules.json:114). The public splits
    only show 1.5 and -1; 0 and 2.5 are added here, on SVC-LAB (max 3), so the
    whole-number check is the only thing that can fail.
    """
    for quantity in (1.5, 2.5, 0, -1):
        claim = base_claim()
        claim["lines"] = [
            line(
                service_code="SVC-LAB",
                quantity=quantity,
                unit_price=120,
                net_amount=120 * quantity if quantity > 0 else 0,
            )
        ]
        entry = record(claim, "R013")
        assert entry["status"] == FAIL, quantity
        assert entry["affected_line_ids"] == ["L1"], quantity


def test_r013_fails_on_a_zero_price_rather_than_abstaining() -> None:
    """R013: "unit_price must be greater than zero ... A known violation fails.
    Missing values ... leave UNABLE_TO_ASSESS" (docs/04_Rulebook.md:138-140). A
    zero price is present and therefore a violation, not an abstention.
    """
    claim = base_claim()
    claim["lines"][0].update(unit_price=0, net_amount=0)
    claim["total_amount"] = 0
    entry = record(claim, "R013")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1"]


def test_r013_passes_at_the_maximum_unit_price_and_fails_one_cent_above() -> None:
    """R013: "unit_price ... at most policy.max_unit_price[service_code] ...
    Equality at the maximum passes" (docs/04_Rulebook.md:138-140;
    rules/rules.json:114). SVC-CONSULT caps at 350 SAR (docs/04_Rulebook.md:27).
    """
    claim = base_claim()
    claim["lines"][0].update(unit_price=350, net_amount=350)
    claim["total_amount"] = 350
    assert status_of(claim, "R013") == PASS
    claim["lines"][0].update(unit_price=350.01, net_amount=350.01)
    claim["total_amount"] = 350.01
    entry = record(claim, "R013")
    assert entry["status"] == FAIL
    assert entry["affected_line_ids"] == ["L1"]


# Resolution: the pack's transport contract accepts int OR float for quantity
# (pack src/engine_core.py:87), so rejecting a mathematically whole JSON 2.0 as
# "not an integer" would contradict the contract our own validator enforces.
def test_r013_accepts_a_quantity_written_as_an_integral_float() -> None:
    """R013: "Every quantity must be a positive integer" (docs/04_Rulebook.md:138;
    rules/rules.json:114) does not say whether a JSON ``2.0`` — mathematically
    whole but typed as a float — counts, and the transport contract validates
    quantity as int OR float (src/engine_core.py:87). No public split uses a float
    quantity, so no gold can arbitrate; this pins the engine's reading (integral
    value -> passes), on SVC-LAB (max 3).
    """
    claim = base_claim()
    claim["lines"] = [line(service_code="SVC-LAB", quantity=2.0, unit_price=120, net_amount=240)]
    claim["total_amount"] = 240
    entry = record(claim, "R013")
    assert entry["status"] == PASS
    assert entry["affected_line_ids"] == []
