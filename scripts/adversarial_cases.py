"""Adversarial and boundary cases against the deterministic engine.

WHAT THIS IS FOR
----------------
The pack's own splits are *representative*: they exercise the rules, but they are
generated from one distribution, so passing them proves the engine agrees with the
labelling programme - not that it survives the edges. This script builds cases
where the interesting question is a SINGLE boundary the rulebook words precisely:

    R003  "within coverage.start_date and coverage.end_date, both inclusive"
    R007  "a difference of at most 0.01 SAR passes" / "ROUND_HALF_UP"
    R009  "aggregate quantity ... <= max_quantity" / "inclusive valid_from/valid_to"
    R013  "quantity must be at most ...; equality at the maximum passes"
    R014  "submission_date minus the latest service_date must be <= window"

Each case states the status its rule MUST return, straight from that wording. A
case that comes back different is either a false negative (we let a real violation
pass) or a false positive (we failed a claim that is fine) - both are the failure
modes the challenge scores.

It also fires transport-level and robustness cases: malformed envelopes that must be
refused before any rule runs, and hostile-but-legal payloads (huge strings, extreme
dates, 200 lines) that must not crash the engine or produce a record that violates
its own contract.

HOW IT RUNS
-----------
In process, against the rule catalogue in CLAIMGUARD_RULES_DIR (or the committed
copy at tests/edu/fixtures/pack_reference). No database, no pack dataset, no network.

Exit codes
----------
0  every case behaved as the rulebook says
1  at least one mismatch, crash, or contract violation (the table says which)

Usage
-----
    uv run python scripts/adversarial_cases.py
    uv run python scripts/adversarial_cases.py --rules-dir <pack>/rules --verbose
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # run as a script, not a module
    sys.path.insert(0, str(REPO_ROOT))

from claimguard.edu.emit import validate_record  # noqa: E402
from claimguard.edu.engine import evaluate_claim  # noqa: E402
from claimguard.edu.envelope import TransportError, validate_transport  # noqa: E402
from claimguard.edu.policy import RuleContext  # noqa: E402

#: The committed copy of the pack's catalogue, so the script needs no deliverable.
FALLBACK_RULES_DIR: Final = REPO_ROOT / "tests" / "edu" / "fixtures" / "pack_reference"


def _line(text: str = "") -> None:
    """Write one line to stdout (ruff's T20 forbids ``print`` in this tree)."""
    sys.stdout.write(text + "\n")


# --------------------------------------------------------------------------- base


def base_claim() -> dict[str, Any]:
    """One claim that is clean for EDU-BASIC: LAB needs no authorization, no document.

    Every case below starts from this object, so a mismatch can only come from the
    single mutation the case applies.
    """
    return {
        "schema_version": "1.0.0",
        "claim_id": "CG-ADVERSARIAL",
        "invoice_number": "INV-ADVERSARIAL",
        "patient_id": "PAT-ADV-1",
        "member_id": "MEM-ADV-1",
        "provider_id": "EDU-PROV-01",
        "payer_id": "EDU-PAYER",
        "policy_id": "EDU-BASIC",
        "diagnosis_code": "DX-EDU-01",
        "submission_date": "2026-06-01",
        "currency": "SAR",
        "total_amount": 240,
        "coverage": {
            "coverage_id": "COV-ADV-1",
            "status": "active",
            "beneficiary_patient_id": "PAT-ADV-1",
            "member_id": "MEM-ADV-1",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        "lines": [
            {
                "line_id": "L1",
                "service_code": "SVC-LAB",
                "service_date": "2026-05-25",
                "modifier": None,
                "quantity": 2,
                "unit_price": 120,
                "net_amount": 240,
                "authorization_id": None,
            },
        ],
        "authorizations": [],
        "attachments": [],
        "notes": "Synthetic adversarial case. No real patient or payer information.",
    }


def with_line(claim: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """A copy of ``claim`` whose first line carries ``overrides``."""
    out = copy.deepcopy(claim)
    out["lines"][0].update(overrides)
    return out


def imaging_claim(**line_overrides: Any) -> dict[str, Any]:
    """A claim whose only line is SVC-IMAGE: authorization AND imaging-report required.

    Kept arithmetic-clean (1 x 1500 = 1500) so R007/R012 do not add noise.
    """
    out = base_claim()
    out["claim_id"] = "CG-ADVERSARIAL-IMG"
    out["total_amount"] = 1500
    out["lines"] = [
        {
            "line_id": "L1",
            "service_code": "SVC-IMAGE",
            "service_date": "2026-05-25",
            "modifier": None,
            "quantity": 1,
            "unit_price": 1500,
            "net_amount": 1500,
            "authorization_id": "AUTH-ADV-1",
        }
    ]
    out["lines"][0].update(line_overrides)
    out["authorizations"] = [
        {
            "authorization_id": "AUTH-ADV-1",
            "patient_id": "PAT-ADV-1",
            "service_code": "SVC-IMAGE",
            "status": "approved",
            "valid_from": "2026-05-01",
            "valid_to": "2026-06-30",
            "max_quantity": 5,
        }
    ]
    out["attachments"] = [
        {
            "attachment_id": "DOC-ADV-1",
            "type": "imaging-report",
            "patient_id": "PAT-ADV-1",
            "service_code": "SVC-IMAGE",
            "service_date": "2026-05-25",
            "document_status": "final",
            "text": "SYNTHETIC ADVERSARIAL DOCUMENT.",
        }
    ]
    return out


# ------------------------------------------------------------------------ cases


@dataclass(frozen=True)
class Case:
    """One adversarial input and what the rulebook says must come back."""

    name: str
    claim: dict[str, Any]
    rule: str | None
    expected: str | None
    note: str = ""


def _rule_cases() -> list[Case]:
    b = base_claim()
    cases: list[Case] = []

    # --- R002 chronology: service_date must be on or before submission_date; equality passes
    cases += [
        Case(
            "R002 service == submission (equality passes)",
            with_line(b, service_date="2026-06-01"),
            "R002",
            "PASS",
        ),
        Case(
            "R002 service one day after submission",
            with_line(b, service_date="2026-06-02"),
            "R002",
            "FAIL",
        ),
        Case("R002 service_date null", with_line(b, service_date=None), "R002", "UNABLE_TO_ASSESS"),
        Case(
            "R001 service_date null is a known absence",
            with_line(b, service_date=None),
            "R001",
            "FAIL",
        ),
    ]

    # --- R003 coverage: "every service_date must be within start_date and end_date, both inclusive"
    cases += [
        Case(
            "R003 service == coverage.start (inclusive)",
            with_line(b, service_date="2026-01-01"),
            "R003",
            "PASS",
        ),
        Case(
            "R003 service == coverage.end (inclusive)",
            with_line(b, service_date="2026-12-31"),
            "R003",
            "PASS",
        ),
        Case(
            "R003 service one day before coverage start",
            with_line(b, service_date="2025-12-31"),
            "R003",
            "FAIL",
        ),
        Case(
            "R003 service one day after coverage end",
            with_line(b, service_date="2027-01-01"),
            "R003",
            "FAIL",
        ),
        Case(
            "R003 coverage.status terminated",
            _cov(b, status="terminated"),
            "R003",
            "FAIL",
        ),
        Case("R003 coverage.status null", _cov(b, status=None), "R003", "UNABLE_TO_ASSESS"),
        Case("R003 coverage.end_date null", _cov(b, end_date=None), "R003", "UNABLE_TO_ASSESS"),
        Case("R003 coverage.start_date null", _cov(b, start_date=None), "R003", "UNABLE_TO_ASSESS"),
    ]

    # --- R004 identifiers must match exactly
    cases += [
        Case(
            "R004 member_id mismatch",
            with_line(b, quantity=2) | {"member_id": "MEM-OTHER"},
            "R004",
            "FAIL",
        ),
        Case(
            "R004 beneficiary mismatch", _cov(b, beneficiary_patient_id="PAT-OTHER"), "R004", "FAIL"
        ),
        Case("R004 absent comparison input", _cov(b, member_id=None), "R004", "UNABLE_TO_ASSESS"),
    ]

    # --- R005 provider must be in the supplied network
    cases += [
        Case(
            "R005 provider outside the network", b | {"provider_id": "EDU-PROV-99"}, "R005", "FAIL"
        ),
    ]

    # --- R006 duplicates: (service_code, service_date, modifier), null modifier -> ""
    def two_lines(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
        out = copy.deepcopy(b)
        out["claim_id"] = "CG-ADVERSARIAL-DUP"
        first = {
            **{
                "line_id": "L1",
                "service_code": "SVC-LAB",
                "service_date": "2026-05-25",
                "modifier": None,
                "quantity": 2,
                "unit_price": 120,
                "net_amount": 240,
                "authorization_id": None,
            },
            **first,
        }
        second = {
            **{
                "line_id": "L2",
                "service_code": "SVC-LAB",
                "service_date": "2026-05-25",
                "modifier": None,
                "quantity": 1,
                "unit_price": 120,
                "net_amount": 120,
                "authorization_id": None,
            },
            **second,
        }
        out["lines"] = [first, second]
        out["total_amount"] = first["net_amount"] + second["net_amount"]
        return out

    cases += [
        Case("R006 identical code/date/modifier", two_lines({}, {}), "R006", "FAIL"),
        Case(
            "R006 same code and date, different modifier",
            two_lines({}, {"modifier": "M1"}),
            "R006",
            "PASS",
        ),
        Case(
            "R006 null modifier vs empty modifier", two_lines({}, {"modifier": ""}), "R006", "FAIL"
        ),
        Case(
            "R006 same code, different date",
            two_lines({}, {"service_date": "2026-05-26"}),
            "R006",
            "PASS",
        ),
        Case("R006 three identical lines", _triple(b), "R006", "FAIL"),
    ]

    # --- R007 line arithmetic: "<= 0.01 passes", ROUND_HALF_UP
    cases += [
        Case(
            "R007 net off by exactly 0.01",
            with_line(b, net_amount=240.01) | {"total_amount": 240.01},
            "R007",
            "PASS",
        ),
        Case(
            "R007 net off by exactly 0.02",
            with_line(b, net_amount=240.02) | {"total_amount": 240.02},
            "R007",
            "FAIL",
        ),
        Case(
            "R007 half-up rounding 3 x 0.335 = 1.01",
            with_line(b, quantity=3, unit_price=0.335, net_amount=1.01) | {"total_amount": 1.01},
            "R007",
            "PASS",
        ),
        Case(
            "R007 float noise 3 x 0.1 = 0.3",
            with_line(b, quantity=3, unit_price=0.1, net_amount=0.30000000000000004)
            | {"total_amount": 0.30000000000000004},
            "R007",
            "PASS",
        ),
        Case("R007 net_amount null", with_line(b, net_amount=None), "R007", "UNABLE_TO_ASSESS"),
        Case("R007 quantity null", with_line(b, quantity=None), "R007", "UNABLE_TO_ASSESS"),
    ]

    # --- R008/R009 authorizations (imaging: authorization required)
    ok_img = imaging_claim()
    cases += [
        Case(
            "R008 required authorization reference empty",
            imaging_claim(authorization_id=""),
            "R008",
            "FAIL",
        ),
        Case(
            "R008 required authorization reference null",
            imaging_claim(authorization_id=None),
            "R008",
            "FAIL",
        ),
        Case("R008 non-required service is not applicable", b, "R008", "NOT_APPLICABLE"),
        Case("R009 referenced authorization is absent", _no_auth(ok_img), "R009", "FAIL"),
        Case("R009 authorization status pending", _auth(ok_img, status="pending"), "R009", "FAIL"),
        Case(
            "R009 valid_to == service_date (inclusive)",
            _auth(ok_img, valid_to="2026-05-25"),
            "R009",
            "PASS",
        ),
        Case(
            "R009 valid_to one day before service",
            _auth(ok_img, valid_to="2026-05-24"),
            "R009",
            "FAIL",
        ),
        Case(
            "R009 valid_from == service_date (inclusive)",
            _auth(ok_img, valid_from="2026-05-25"),
            "R009",
            "PASS",
        ),
        Case(
            "R009 valid_from one day after service",
            _auth(ok_img, valid_from="2026-05-26"),
            "R009",
            "FAIL",
        ),
        Case(
            "R009 authorization service_code mismatch",
            _auth(ok_img, service_code="SVC-LAB"),
            "R009",
            "FAIL",
        ),
        Case(
            "R009 authorization patient mismatch",
            _auth(ok_img, patient_id="PAT-OTHER"),
            "R009",
            "FAIL",
        ),
        Case(
            "R009 aggregate quantity == max_quantity", _auth(ok_img, max_quantity=1), "R009", "PASS"
        ),
        Case(
            "R009 aggregate quantity exceeds max by one",
            _auth(ok_img, max_quantity=0),
            "R009",
            "FAIL",
        ),
        Case(
            "R009 line reference null while R008 fails",
            imaging_claim(authorization_id=None),
            "R009",
            "UNABLE_TO_ASSESS",
        ),
    ]

    # --- R010 required documents (imaging-report for SVC-IMAGE)
    cases += [
        Case("R010 required document present and final", ok_img, "R010", "PASS"),
        Case(
            "R010 matching attachment all draft",
            _doc(ok_img, document_status="draft"),
            "R010",
            "UNABLE_TO_ASSESS",
        ),
        Case("R010 attachments empty", ok_img | {"attachments": []}, "R010", "FAIL"),
        Case(
            "R010 attachment for another patient",
            _doc(ok_img, patient_id="PAT-OTHER"),
            "R010",
            "FAIL",
        ),
        Case(
            "R010 attachment wrong service_code",
            _doc(ok_img, service_code="SVC-LAB"),
            "R010",
            "FAIL",
        ),
        Case(
            "R010 attachment wrong service_date",
            _doc(ok_img, service_date="2026-05-24"),
            "R010",
            "FAIL",
        ),
        Case("R010 attachment wrong type", _doc(ok_img, type="service-note"), "R010", "FAIL"),
        Case("R010 no required document is not applicable", b, "R010", "NOT_APPLICABLE"),
    ]

    # --- R011 service catalogue
    cases += [
        Case("R011 unknown service code", with_line(b, service_code="SVC-NOPE"), "R011", "FAIL"),
        Case("R011 service_code null", with_line(b, service_code=None), "R011", "UNABLE_TO_ASSESS"),
    ]

    # --- R012 claim total
    cases += [
        Case("R012 total matches exactly", b, "R012", "PASS"),
        Case("R012 total off by exactly 0.01", b | {"total_amount": 240.01}, "R012", "PASS"),
        Case("R012 total off by exactly 0.02", b | {"total_amount": 240.02}, "R012", "FAIL"),
        Case("R012 total_amount null", b | {"total_amount": None}, "R012", "UNABLE_TO_ASSESS"),
        Case("R012 two lines, total ignores one", _two_clean(b), "R012", "FAIL"),
    ]

    # --- R013 quantity and price limits (LAB: max 260 unit, 3 per line)
    cases += [
        Case(
            "R013 unit_price == max (260)",
            with_line(b, unit_price=260, net_amount=520) | {"total_amount": 520},
            "R013",
            "PASS",
        ),
        Case(
            "R013 unit_price one over max (261)",
            with_line(b, unit_price=261, net_amount=522) | {"total_amount": 522},
            "R013",
            "FAIL",
        ),
        Case(
            "R013 unit_price zero",
            with_line(b, unit_price=0, net_amount=0) | {"total_amount": 0},
            "R013",
            "FAIL",
        ),
        Case(
            "R013 quantity == max (3)",
            with_line(b, quantity=3, net_amount=360) | {"total_amount": 360},
            "R013",
            "PASS",
        ),
        Case(
            "R013 quantity == max + 1 (4)",
            with_line(b, quantity=4, net_amount=480) | {"total_amount": 480},
            "R013",
            "FAIL",
        ),
        Case(
            "R013 quantity zero",
            with_line(b, quantity=0, net_amount=0) | {"total_amount": 0},
            "R013",
            "FAIL",
        ),
        Case(
            "R013 quantity negative",
            with_line(b, quantity=-2, net_amount=-240) | {"total_amount": -240},
            "R013",
            "FAIL",
        ),
    ]

    # --- R014 submission window (EDU-BASIC: 30 days)
    cases += [
        Case("R014 lag == window (30 days)", b | {"submission_date": "2026-06-24"}, "R014", "PASS"),
        Case(
            "R014 lag == window + 1 (31 days)",
            b | {"submission_date": "2026-06-25"},
            "R014",
            "FAIL",
        ),
    ]

    # --- R015 currency
    cases += [
        Case("R015 currency SAR", b, "R015", "PASS"),
        Case("R015 currency USD", b | {"currency": "USD"}, "R015", "FAIL"),
    ]
    return cases


def _cov(claim: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    out = copy.deepcopy(claim)
    out["coverage"].update(overrides)
    return out


def _auth(claim: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    out = copy.deepcopy(claim)
    out["authorizations"][0].update(overrides)
    return out


def _no_auth(claim: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(claim)
    out["authorizations"] = []
    return out


def _doc(claim: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    out = copy.deepcopy(claim)
    out["attachments"][0].update(overrides)
    return out


def _triple(claim: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(claim)
    line = out["lines"][0]
    out["lines"] = [dict(line, line_id=f"L{i}") for i in (1, 2, 3)]
    out["claim_id"] = "CG-ADVERSARIAL-TRIPLE"
    out["total_amount"] = line["net_amount"] * 3
    return out


def _two_clean(claim: dict[str, Any]) -> dict[str, Any]:
    """Two valid, non-duplicate lines whose sum the total deliberately ignores."""
    out = copy.deepcopy(claim)
    out["claim_id"] = "CG-ADVERSARIAL-TWOLINE"
    out["lines"] = [
        {
            "line_id": "L1",
            "service_code": "SVC-LAB",
            "service_date": "2026-05-25",
            "modifier": None,
            "quantity": 2,
            "unit_price": 120,
            "net_amount": 240,
            "authorization_id": None,
        },
        {
            "line_id": "L2",
            "service_code": "SVC-CONSULT",
            "service_date": "2026-05-26",
            "modifier": None,
            "quantity": 1,
            "unit_price": 180,
            "net_amount": 180,
            "authorization_id": None,
        },
    ]
    out["total_amount"] = 240  # should be 420
    return out


def _transport_cases() -> list[Case]:
    b = base_claim()
    drop = copy.deepcopy(b)
    del drop["currency"]
    extra = copy.deepcopy(b)
    extra["surprise"] = "not in the envelope"
    dupid = copy.deepcopy(b)
    dupid["lines"] = [dict(b["lines"][0]), dict(b["lines"][0])]
    lineno = copy.deepcopy(b)
    del lineno["lines"][0]["net_amount"]
    empty = copy.deepcopy(b)
    empty["lines"] = []
    extended = copy.deepcopy(b)
    extended["__proto__"] = {"polluted": True}
    not_a_date = with_line(b, service_date="not-a-date")
    null_provider = b | {"provider_id": None}
    null_submission = b | {"submission_date": None}
    null_currency = b | {"currency": None}
    null_auth_record = _auth(imaging_claim(), authorization_id=None)
    return [
        Case("transport: missing top-level key (currency)", drop, None, "REFUSED"),
        Case("transport: extra top-level key", extra, None, "REFUSED"),
        Case("transport: duplicate line_id", dupid, None, "REFUSED"),
        Case("transport: line missing net_amount key", lineno, None, "REFUSED"),
        Case("transport: empty lines array", empty, None, "REFUSED"),
        Case("transport: __proto__ key", extended, None, "REFUSED"),
        # Structural keys are non-nullable by contract (docs/03_Data_Dictionary.md): a
        # null here is a transport defect, so the rulebook's "missing input ->
        # UNABLE_TO_ASSESS" is unreachable for them BY DESIGN. The business values that
        # the rules must abstain on (invoice_number, member_id, diagnosis_code, line
        # service_date, unit_price, and the line's authorization reference) stay nullable.
        Case("transport: structural null provider_id", null_provider, None, "REFUSED"),
        Case("transport: structural null submission_date", null_submission, None, "REFUSED"),
        Case("transport: structural null currency", null_currency, None, "REFUSED"),
        Case("transport: line service_date not a date", not_a_date, None, "REFUSED"),
        Case("transport: authorization record with a null id", null_auth_record, None, "REFUSED"),
    ]


def _robustness_cases() -> list[Case]:
    b = base_claim()
    many = copy.deepcopy(b)
    codes = ["SVC-LAB", "SVC-CONSULT", "SVC-PHARM"]
    many["lines"] = [
        {
            "line_id": f"L{i}",
            "service_code": codes[i % 3],
            "service_date": f"2026-05-{(i % 27) + 1:02d}",
            "modifier": str(i),
            "quantity": 1,
            "unit_price": 100,
            "net_amount": 100,
            "authorization_id": None,
        }
        for i in range(1, 201)
    ]
    many["total_amount"] = 20000
    many["claim_id"] = "CG-ADVERSARIAL-200"

    return [
        Case("robust: 100k-character notes", b | {"notes": "A" * 100_000}, None, None),
        Case(
            "robust: markup and control characters in notes",
            b | {"notes": "<script>alert(1)</script>\x00\u202e\u0007'; DROP TABLE claims;--"},
            None,
            None,
        ),
        Case("robust: 200 service lines", many, None, None),
        Case(
            "robust: amounts at 1e12",
            with_line(b, unit_price=1e12, net_amount=2e12) | {"total_amount": 2e12},
            None,
            None,
        ),
        Case("robust: date 1900-01-01", with_line(b, service_date="1900-01-01"), None, None),
        Case("robust: date 9999-12-31", with_line(b, service_date="9999-12-31"), None, None),
        Case(
            "robust: unicode identifiers",
            b | {"patient_id": "PAT-ÜNICODE-🚀", "member_id": "MEM-ÜNICODE-🚀"},
            None,
            None,
        ),
        Case(
            "robust: 10k-character service_code",
            with_line(b, service_code="SVC-" + "X" * 10_000),
            None,
            None,
        ),
        Case(
            "robust: deeply nested attachment text",
            b
            | {
                "attachments": [
                    {
                        "attachment_id": "DOC-X",
                        "type": "service-note",
                        "patient_id": "PAT-ADV-1",
                        "service_code": "SVC-LAB",
                        "service_date": "2026-05-25",
                        "document_status": "final",
                        "text": '{"a":' * 500 + "1" + "}" * 500,
                    }
                ]
            },
            None,
            None,
        ),
    ]


# ----------------------------------------------------------------------- running


@dataclass
class Outcome:
    case: Case
    observed: str
    verdict: str  # OK | MISMATCH | CRASH | CONTRACT
    detail: str = ""
    statuses: dict[str, str] | None = None


def run_case(case: Case, ctx: RuleContext) -> Outcome:
    """Evaluate one case; never raises - a crash IS the finding."""
    payload = case.claim
    try:
        validate_transport(payload)
    except TransportError as exc:
        if case.expected == "REFUSED":
            return Outcome(case, "REFUSED", "OK", str(exc)[:60])
        return Outcome(case, "REFUSED", "MISMATCH", f"transport refused a legal change: {exc}")
    except Exception as exc:  # noqa: BLE001 - any other exception is a finding
        return Outcome(
            case, "CRASH", "CRASH", f"validate_transport raised {type(exc).__name__}: {exc}"
        )

    if case.expected == "REFUSED":
        return Outcome(case, "ACCEPTED", "MISMATCH", "transport accepted malformed input")

    try:
        raw = list(evaluate_claim(payload, ctx))
    except Exception as exc:  # noqa: BLE001
        return Outcome(case, "CRASH", "CRASH", f"evaluate_claim raised {type(exc).__name__}: {exc}")

    try:
        # Exactly what the API does: every record must survive its own contract
        # validator against the ORIGINAL object before anything is served.
        records = [validate_record(record, payload) for record in raw]
    except Exception as exc:  # noqa: BLE001
        return Outcome(case, "CONTRACT", "CONTRACT", f"record violates its own contract: {exc}")

    if len(records) != 15:
        return Outcome(case, f"{len(records)} records", "CONTRACT", "expected exactly 15 records")

    statuses = {
        r.rule_id: r.status.value if hasattr(r.status, "value") else str(r.status) for r in records
    }
    if case.rule is None:
        interesting = {k: v for k, v in statuses.items() if v in ("FAIL", "UNABLE_TO_ASSESS")}
        return Outcome(
            case, "15 records, contract valid", "OK", json.dumps(interesting)[:90], statuses
        )

    observed = statuses.get(case.rule, "<missing>")
    verdict = "OK" if observed == case.expected else "MISMATCH"
    return Outcome(
        case, observed, verdict, "" if verdict == "OK" else f"expected {case.expected}", statuses
    )


def all_cases() -> list[Case]:
    """Every case: rule boundaries, transport refusals, and robustness probes."""
    return _rule_cases() + _transport_cases() + _robustness_cases()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Adversarial and boundary cases for the engine.")
    parser.add_argument("--rules-dir", default=None, help="rule catalogue directory")
    parser.add_argument("--verbose", action="store_true", help="print every status per case")
    parser.add_argument("--only", default=None, help="run only cases whose name contains this")
    args = parser.parse_args(argv)

    rules_dir = args.rules_dir or os.environ.get("CLAIMGUARD_RULES_DIR") or str(FALLBACK_RULES_DIR)
    ctx = RuleContext.from_rules_dir(rules_dir)
    _line("claimguard adversarial cases")
    _line(f"  catalogue : {rules_dir}")
    _line(
        f"  rules: {len(ctx.rules)}  services: {len(ctx.services)}  policies: {len(ctx.policies)}"
    )
    _line()

    cases = all_cases()
    if args.only:
        cases = [c for c in cases if args.only.lower() in c.name.lower()]

    started = time.perf_counter()
    outcomes = [run_case(case, ctx) for case in cases]
    elapsed = time.perf_counter() - started

    width = max(len(o.case.name) for o in outcomes)
    _line(f"{'case'.ljust(width)}  {'expected':<18} {'observed':<18} verdict")
    _line("-" * (width + 60))
    for o in outcomes:
        expected = o.case.expected or "(no crash, contract valid)"
        mark = "" if o.verdict == "OK" else "  <<< " + o.detail
        _line(f"{o.case.name.ljust(width)}  {expected:<18} {o.observed:<18} {o.verdict}{mark}")
        if args.verbose and o.statuses:
            failing = {k: v for k, v in o.statuses.items() if v != "PASS"}
            _line(f"{'':>{width}}    non-PASS: {json.dumps(failing)}")

    bad = [o for o in outcomes if o.verdict != "OK"]
    _line()
    good = len(outcomes) - len(bad)
    _line(f"{good}/{len(outcomes)} cases behaved as the rulebook says ({elapsed:.2f}s)")
    if bad:
        _line(f"{len(bad)} case(s) need a look:")
        for o in bad:
            _line(f"  - {o.case.name}: {o.detail}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
