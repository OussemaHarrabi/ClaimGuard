"""Build the demonstration claim set, and prove each claim produces the findings it is meant to.

WHY A GENERATOR RATHER THAN SEVEN HAND-WRITTEN FILES
----------------------------------------------------
A demo claim that does not produce the finding the presenter narrates is worse than no demo at
all, and hand-written JSON drifts the moment a catalogue value changes. So each claim below is
declared with the findings it is MEANT to produce, the engine is run over it here, and any
disagreement fails this script. The artefacts under ``examples/demo/`` are the output.

WHAT THE SET COVERS
-------------------
One clean claim (to show that a valid claim is not flagged), and six with one to three deliberate
defects each - no two claims relying on the same rule, so the set exercises ten of the fifteen
checks across the categories the challenge names: missing data, inconsistent data, duplicate data
and unsupported data, plus the abstention status (``UNABLE_TO_ASSESS``), which is the one people
misread as a pass.

Every bad claim also ships its corrected envelope, so the correction and recheck step can be
demonstrated by pasting one file rather than editing JSON on camera.

Usage
-----
    uv run python scripts/make_demo_claims.py            # write the artefacts, verify as it goes
    uv run python scripts/make_demo_claims.py --check     # verify only; write nothing

Exit codes
----------
0  every claim produced exactly the findings it declares
1  a claim disagreed with its declaration (the difference is printed), or an artefact is stale
2  the engine did not return fifteen records for a claim (the coverage contract)
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # run as a script, not a module
    sys.path.insert(0, str(REPO_ROOT))

from claimguard.edu.engine import evaluate_claim  # noqa: E402
from claimguard.edu.policy import RuleContext  # noqa: E402

DEFAULT_OUT: Final = REPO_ROOT / "examples" / "demo"
RULES_DIR: Final = REPO_ROOT / "tests" / "edu" / "fixtures" / "pack_reference"

#: Statuses that mean "a human has to look at this", i.e. everything the demo narrates.
NOTABLE: Final = ("FAIL", "UNABLE_TO_ASSESS")

#: How each review action reads on the interface, so the sheet names the button as the reviewer sees
#: it rather than as the API spells it.
ACTION_LABEL: Final[dict[str, str]] = {
    "confirm_issue": "Confirm issue",
    "dismiss_with_reason": "Dismiss with reason",
    "request_information": "Request information",
    "mark_corrected_for_recheck": "Mark corrected for recheck",
}


def _line(text: str = "") -> None:
    """Write one line to stdout (ruff's T20 forbids ``print`` in this tree)."""
    sys.stdout.write(text + "\n")


def base_envelope(claim_id: str, *, policy: str = "EDU-PLUS") -> dict[str, Any]:
    """A claim that passes everything: the shape every demonstration case starts from.

    LAB at 2 x 120 = 240, inside a coverage year that contains the service date, submitted a week
    later - chosen so a single edit is the only reason anything is ever flagged.
    """
    patient, member = f"PAT-{claim_id}", f"MEM-{claim_id}"
    return {
        "schema_version": "1.0.0",
        "claim_id": claim_id,
        "invoice_number": f"INV-{claim_id}",
        "patient_id": patient,
        "member_id": member,
        "provider_id": "EDU-PROV-02",
        "payer_id": "EDU-PAYER",
        "policy_id": policy,
        "diagnosis_code": "DX-EDU-02",
        "submission_date": "2026-06-01",
        "currency": "SAR",
        "total_amount": 240,
        "coverage": {
            "coverage_id": f"COV-{claim_id}",
            "status": "active",
            "beneficiary_patient_id": patient,
            "member_id": member,
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
            }
        ],
        "authorizations": [],
        "attachments": [],
        "notes": "Synthetic demonstration claim. No real patient or payer information.",
    }


@dataclass
class Case:
    """One demonstration claim: what it is called, what it breaks, and what must come back."""

    name: str
    claim_id: str
    headline: str
    claim: dict[str, Any]
    expect: dict[str, str]
    fixed: dict[str, Any] | None = None
    fix_notes: list[str] = field(default_factory=list[str])
    #: ``(rule_id, action, reviewer note)`` per finding. The four actions a reviewer has are
    #: request_information, confirm_issue, dismiss_with_reason and mark_corrected_for_recheck; the
    #: sheet spreads them across the set so a demo can show every one, and each entry is legal from
    #: the finding's own review status - a fresh finding allows all four, while a confirmed or
    #: dismissed one allows only request_information and mark_corrected_for_recheck.
    decisions: tuple[tuple[str, str, str], ...] = ()


def _clean() -> Case:
    claim = base_envelope("DEMO-01-CLEAN")
    return Case(
        name="01-clean",
        claim_id=claim["claim_id"],
        headline="A valid claim: nothing is flagged (14 pass, 3 not applicable)",
        claim=claim,
        expect={},
    )


def _coverage_and_window() -> Case:
    claim = base_envelope("DEMO-02-COVERAGE")
    claim["coverage"]["end_date"] = "2026-04-29"  # service is 2026-04-30
    claim["lines"][0]["service_date"] = "2026-04-30"
    claim["submission_date"] = "2026-09-14"  # 137 days after the service date
    fixed = copy.deepcopy(claim)
    fixed["coverage"]["end_date"] = "2026-12-31"
    fixed["submission_date"] = "2026-05-05"
    return Case(
        name="02-coverage-and-window",
        claim_id=claim["claim_id"],
        headline="Coverage ended the day before the service, and the claim was submitted late",
        claim=claim,
        expect={"R003": "FAIL", "R014": "FAIL"},
        fixed=fixed,
        fix_notes=[
            "coverage.end_date  2026-04-29 -> 2026-12-31  (the service date must fall inside it)",
            "submission_date    2026-09-14 -> 2026-05-05   (within 60 days of the service date)",
        ],
        decisions=(
            (
                "R003",
                "confirm_issue",
                "Coverage dates verified against eligibility; the service is outside it.",
            ),
            ("R014", "confirm_issue", "Submission lag confirmed from the dispatch record."),
        ),
    )


def _arithmetic_and_total() -> Case:
    claim = base_envelope("DEMO-03-ARITHMETIC")
    claim["lines"][0]["unit_price"] = 130  # 2 x 130 = 260 ...
    claim["lines"][0]["net_amount"] = 271  # ... but the line says 271
    claim["total_amount"] = 999  # ... and the claim total says 999
    fixed = copy.deepcopy(claim)
    fixed["lines"][0]["net_amount"] = 260
    fixed["total_amount"] = 260
    return Case(
        name="03-arithmetic-and-total",
        claim_id=claim["claim_id"],
        headline="A line that does not add up, and a claim total matching neither line nor itself",
        claim=claim,
        expect={"R007": "FAIL", "R012": "FAIL"},
        fixed=fixed,
        fix_notes=[
            "lines[0].net_amount  271 -> 260   (quantity 2 x unit price 130)",
            "total_amount         999 -> 260   (the sum of the line amounts)",
        ],
        decisions=(
            (
                "R007",
                "confirm_issue",
                "Line amount recomputed: quantity x unit price does not reach it.",
            ),
            (
                "R012",
                "mark_corrected_for_recheck",
                "Total corrected on the new version; rechecking it.",
            ),
        ),
    )


def _duplicate_and_limit() -> Case:
    claim = base_envelope("DEMO-04-DUPLICATE")
    claim["lines"] = [
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
            "service_code": "SVC-LAB",
            "service_date": "2026-05-25",  # same code, same date, same (empty) modifier
            "modifier": None,
            "quantity": 4,  # and one line exceeds the fictional maximum of 3
            "unit_price": 120,
            "net_amount": 480,
            "authorization_id": None,
        },
    ]
    claim["total_amount"] = 720
    fixed = copy.deepcopy(claim)
    fixed["lines"][1]["service_date"] = "2026-05-26"  # a different day is no longer a duplicate
    fixed["lines"][1]["quantity"] = 3  # at the maximum, which passes
    fixed["lines"][1]["net_amount"] = 360
    fixed["total_amount"] = 600
    return Case(
        name="04-duplicate-and-limit",
        claim_id=claim["claim_id"],
        headline="Two identical service lines, and a quantity above the fictional maximum",
        claim=claim,
        expect={"R006": "FAIL", "R013": "FAIL"},
        fixed=fixed,
        fix_notes=[
            "lines[1].service_date  2026-05-25 -> 2026-05-26  (two services need two dates)",
            "lines[1].quantity      4 -> 3                     (the policy maximum for SVC-LAB)",
            "lines[1].net_amount    480 -> 360                 (3 x 120)",
            "total_amount           720 -> 600                 (240 + 360)",
        ],
        decisions=(
            (
                "R006",
                "dismiss_with_reason",
                "Clinic confirmed two separate services on the same day; not a duplicate.",
            ),
            ("R013", "confirm_issue", "Quantity is above the fictional maximum for this service."),
        ),
    )


def _authorization_and_document() -> Case:
    claim = base_envelope("DEMO-05-IMAGING")
    claim["total_amount"] = 1500
    claim["lines"] = [
        {
            "line_id": "L1",
            "service_code": "SVC-IMAGE",  # the policy requires an authorization AND a report
            "service_date": "2026-05-20",
            "modifier": None,
            "quantity": 1,
            "unit_price": 1500,
            "net_amount": 1500,
            "authorization_id": None,  # nothing to resolve
        }
    ]
    claim["authorizations"] = []
    claim["attachments"] = []
    fixed = copy.deepcopy(claim)
    fixed["lines"][0]["authorization_id"] = "AUTH-DEMO-05"
    fixed["authorizations"] = [
        {
            "authorization_id": "AUTH-DEMO-05",
            "patient_id": claim["patient_id"],
            "service_code": "SVC-IMAGE",
            "status": "approved",
            "valid_from": "2026-05-01",
            "valid_to": "2026-06-30",
            "max_quantity": 5,
        }
    ]
    fixed["attachments"] = [
        {
            "attachment_id": "DOC-DEMO-05",
            "type": "imaging-report",
            "patient_id": claim["patient_id"],
            "service_code": "SVC-IMAGE",
            "service_date": "2026-05-20",
            "document_status": "final",
            "text": "SYNTHETIC DEMO DOCUMENT. Imaging report supplied for the demonstration claim.",
        }
    ]
    return Case(
        name="05-authorization-and-document",
        claim_id=claim["claim_id"],
        headline="An imaging service with no authorization reference and no accompanying report",
        claim=claim,
        expect={"R008": "FAIL", "R009": "UNABLE_TO_ASSESS", "R010": "FAIL"},
        fixed=fixed,
        fix_notes=[
            "lines[0].authorization_id null -> AUTH-DEMO-05   (the reference the policy demands)",
            "authorizations            [] -> one approved record matching patient and service",
            "attachments               [] -> one final imaging-report for this service and date",
        ],
        decisions=(
            (
                "R008",
                "request_information",
                "Authorization reference absent; requested from the provider.",
            ),
            ("R010", "request_information", "Imaging report absent; requested from the provider."),
        ),
    )


def _catalogue_identity_currency() -> Case:
    claim = base_envelope("DEMO-06-CODE-IDENTITY", policy="EDU-BASIC")
    claim["lines"][0]["service_code"] = "SVC-XRAY"  # not in the fictional catalogue
    claim["coverage"]["member_id"] = "MEM-SOMEONE-ELSE"  # the coverage belongs to another member
    claim["currency"] = "USD"  # the policy is priced in SAR
    fixed = copy.deepcopy(claim)
    fixed["lines"][0]["service_code"] = "SVC-LAB"
    fixed["coverage"]["member_id"] = claim["member_id"]
    fixed["currency"] = "SAR"
    return Case(
        name="06-code-identity-currency",
        claim_id=claim["claim_id"],
        headline=(
            "A service code outside the catalogue, a coverage naming another member, and the wrong "
            "currency - and the four checks that can only ABSTAIN while the code is unknown"
        ),
        claim=claim,
        # The unknown code is not one finding: every check that resolves the service through the
        # catalogue (its authorization requirement, its report requirement, its price and quantity
        # limits) has nothing to resolve and abstains. That cascade is the point of showing this
        # claim - one field, and five abstentions plus three failures clear together.
        expect={
            "R004": "FAIL",
            "R008": "UNABLE_TO_ASSESS",
            "R009": "UNABLE_TO_ASSESS",
            "R010": "UNABLE_TO_ASSESS",
            "R011": "FAIL",
            "R013": "UNABLE_TO_ASSESS",
            "R015": "FAIL",
        },
        fixed=fixed,
        fix_notes=[
            "lines[0].service_code  SVC-XRAY -> SVC-LAB   (a code the catalogue contains;",
            "                                              this one change clears R008, R009, R010",
            "                                              and R013, which could only abstain)",
            "                                                    code resolved to nothing)",
            "coverage.member_id     MEM-SOMEONE-ELSE -> the member_id above (must be equal)",
            "currency                 USD -> SAR                   (the policy currency)",
        ],
        decisions=(
            (
                "R011",
                "confirm_issue",
                "Not in the payer catalogue; confirmed against the coding sheet.",
            ),
            (
                "R015",
                "confirm_issue",
                "The policy is priced in SAR; a USD total cannot be processed as submitted.",
            ),
        ),
    )


def _missing_value() -> Case:
    claim = base_envelope("DEMO-07-MISSING")
    claim["lines"][0]["unit_price"] = None  # a required business value, absent
    fixed = copy.deepcopy(claim)
    fixed["lines"][0]["unit_price"] = 120
    return Case(
        name="07-missing-value",
        claim_id=claim["claim_id"],
        headline="A required value missing: the check fails, and the ones that need it abstain",
        claim=claim,
        expect={"R001": "FAIL", "R007": "UNABLE_TO_ASSESS", "R013": "UNABLE_TO_ASSESS"},
        fixed=fixed,
        fix_notes=[
            "lines[0].unit_price  null -> 120   (then 2 x 120 = 240, as the line and total say)",
        ],
        decisions=(
            (
                "R001",
                "request_information",
                "Unit price missing from the source; requested from the provider.",
            ),
            (
                "R007",
                "request_information",
                "The line cannot be computed until the unit price is supplied.",
            ),
        ),
    )


def cases() -> list[Case]:
    """The demonstration set, in the order a presenter should upload them."""
    return [
        _clean(),
        _coverage_and_window(),
        _arithmetic_and_total(),
        _duplicate_and_limit(),
        _authorization_and_document(),
        _catalogue_identity_currency(),
        _missing_value(),
    ]


def statuses(claim: dict[str, Any], context: RuleContext) -> dict[str, str]:
    """Run the engine and return ``{rule_id: status}``, enforcing the fifteen-record contract."""
    records = [dict(record) for record in evaluate_claim(claim, context)]
    if len(records) != 15:
        raise ValueError(f"{claim.get('claim_id')}: {len(records)} records, expected 15")
    return {str(record["rule_id"]): str(record["status"]) for record in records}


def verify(case: Case, context: RuleContext) -> list[str]:
    """Return the ways ``case`` disagrees with what it claims to demonstrate (empty = agrees)."""
    problems: list[str] = []
    produced = statuses(case.claim, context)
    notable = {rule: status for rule, status in produced.items() if status in NOTABLE}
    if notable != case.expect:
        problems.append(
            f"{case.claim_id}: expected {case.expect or '{}'}, engine produced {notable or '{}'}"
        )
    if case.fixed is not None:
        after = statuses(case.fixed, context)
        remaining = {rule: status for rule, status in after.items() if status in NOTABLE}
        if remaining:
            problems.append(
                f"{case.claim_id}: the corrected envelope is still flagged: {remaining}"
            )
    return problems


def render_corrections(verified: list[Case]) -> str:
    """The presenter's sheet: per claim, what is wrong, what to change, and what to press."""
    lines: list[str] = [
        "# Demo corrections — what to change, and what to press",
        "",
        "Every claim under `claims/` has its corrected twin under `corrected/`. To demonstrate the",
        "correction and recheck step: open the claim in **My Queue**, press **Correct claim &",
        "recheck**, select everything in the JSON editor, paste the matching `corrected/` file,",
        "and press **Create version & recheck**. The original version stays; version 2 supersedes",
        "it and the findings should clear.",
        "",
        "| Claim file | Demonstrates | Findings it produces |",
        "|---|---|---|",
    ]
    for case in verified:
        found = (
            ", ".join(f"`{rule}` {status}" for rule, status in case.expect.items())
            or "none — 14 PASS, 3 NOT_APPLICABLE"
        )
        lines.append(f"| `claims/{case.name}.json` | {case.headline} | {found} |")

    lines += ["", "---", ""]
    for case in verified:
        lines += [f"## `{case.name}.json` — {case.headline}", ""]
        if not case.expect:
            lines += [
                "**Nothing to fix.** This is the control: a complete, consistent claim that",
                "the engine does not flag. Use it to show that a valid claim passes, and that the",
                "remaining statuses are `NOT_APPLICABLE` rather than `PASS`.",
                "",
            ]
            continue
        lines += ["**What the engine reports**", ""]
        for rule, status in case.expect.items():
            lines.append(f"- `{rule}` → **{status}**")
        lines += ["", "**What to change** (field → new value)", "", "```text"]
        lines += case.fix_notes
        lines += [
            "```",
            "",
            f"**Paste-ready:** `corrected/{case.name}-fixed.json`",
            "",
            "**Suggested reviewer interaction** - across the set this uses all four buttons a",
            "reviewer has:",
            "",
        ]
        by_rule = {rule: (action, note) for rule, action, note in case.decisions}
        for rule in case.expect:
            action, note = by_rule.get(rule, ("", ""))
            if action:
                lines.append(f'- `{rule}` → **{ACTION_LABEL[action]}** — "{note}"')
        lines += [
            "",
            "For the **XAI** assistant, these questions stay in scope:",
            '- "Why is this flagged?"',
            '- "What should I check first?"',
            '- "Which line is affected and what did the rule compare?"',
            "",
            'Guardrail: ask *"Should we just pay this claim?"* - it refuses, and says the',
            "decision is a reviewer's and a payer's.",
            "",
        ]
    return "\n".join(lines).rstrip("\n") + "\n"


def render_readme(verified: list[Case]) -> str:
    lines = [
        "# Demonstration kit",
        "",
        "Seven synthetic claims: one clean, six with one to three deliberate defects each, no two",
        "claims relying on the same rule. Every claim here was generated and then **checked by the",
        "engine** (`scripts/make_demo_claims.py`); if a claim stopped producing the findings it",
        "declares, that script fails rather than shipping a demo that narrates something else.",
        "",
        "```text",
        "claims/     upload these (one claim per file, complete ClaimGuard JSON)",
        "corrected/  the same claims with the defects repaired — paste into the correction editor",
        "```",
        "",
        "**The flow these are built for:** Document Intake -> upload a file -> it waits in",
        "the list (nothing runs yet) -> press **Start check** on that row -> it is checked",
        "and appears in **My Queue** -> read the findings and evidence, ask **XAI**, decide,",
        "correct and recheck.",
        "",
        "The presenter's sheet - every claim, what it demonstrates, the fields to change, the",
        "reviewer note and the button to press — is [`CORRECTIONS.md`](CORRECTIONS.md).",
        "",
        "| Claim | Demonstrates |",
        "|---|---|",
    ]
    for case in verified:
        lines.append(f"| `claims/{case.name}.json` | {case.headline} |")
    lines += [
        "",
        "All content is synthetic and refers to a fictional payer; no real patient or payer data",
        "involved. The service codes, policies and limits come from the teaching pack's catalogue.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and verify the demonstration claim set.")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="where to write the artefacts"
    )
    parser.add_argument("--check", action="store_true", help="verify only, write nothing")
    args = parser.parse_args(argv)

    context = RuleContext.from_rules_dir(RULES_DIR)
    built = cases()

    _line("claimguard demonstration claims")
    _line(f"  catalogue : {RULES_DIR.relative_to(REPO_ROOT)}")
    _line()

    problems: list[str] = []
    for case in built:
        produced = statuses(case.claim, context)
        notable = {rule: status for rule, status in produced.items() if status in NOTABLE}
        _line(f"  {case.name:30s} {case.claim_id:22s} {notable or '{}'}")
        problems.extend(verify(case, context))

    _line()
    if problems:
        for problem in problems:
            _line(f"  MISMATCH: {problem}")
        return 1

    corrections = render_corrections(built)
    readme = render_readme(built)
    artefacts: list[tuple[Path, str]] = [
        (args.out / "CORRECTIONS.md", corrections),
        (args.out / "README.md", readme),
    ]
    for case in built:
        artefacts.append(
            (args.out / "claims" / f"{case.name}.json", json.dumps(case.claim, indent=2) + "\n")
        )
        if case.fixed is not None:
            artefacts.append(
                (
                    args.out / "corrected" / f"{case.name}-fixed.json",
                    json.dumps(case.fixed, indent=2) + "\n",
                )
            )

    if args.check:
        stale = [
            path
            for path, content in artefacts
            if path.is_file() and path.read_text(encoding="utf-8") != content
        ]
        missing = [path for path, _ in artefacts if not path.is_file()]
        if stale or missing:
            for path in stale:
                _line(f"  STALE: {path.relative_to(REPO_ROOT)}")
            for path in missing:
                _line(f"  MISSING: {path.relative_to(REPO_ROOT)}")
            return 1
        _line(f"{len(artefacts)} artefact(s) match the generator")
        return 0

    for path, content in artefacts:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _line(f"wrote {len(artefacts)} artefact(s) under {args.out.relative_to(REPO_ROOT)}")
    _line(
        "every claim produced exactly the findings it declares, and every corrected twin is clean"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
