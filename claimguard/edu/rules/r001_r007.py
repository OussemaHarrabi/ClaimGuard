"""Deterministic rules R001-R007 (docs/04_Rulebook.md:40-94).

Precedence inside every rule follows the pack's shared conventions
(docs/04_Rulebook.md:9): a *proven* violation gives FAIL; otherwise missing
necessary evidence gives UNABLE_TO_ASSESS; otherwise PASS or NOT_APPLICABLE.
Uncertainty is preserved in the explanation even when another line proves a
failure.

Every pointer is resolved against the ORIGINAL envelope by
:func:`claimguard.edu.emit.make_result`, and ``affected_line_ids`` carry the
stable ``line_id`` values — never array offsets (docs/03_Data_Dictionary.md).
"""

from __future__ import annotations

from typing import Any, Final

from claimguard.edu.emit import (
    SATISFIED,
    format_findings,
    format_findings_with_uncertainty,
    make_result,
)
from claimguard.edu.envelope import (
    MONEY_TOLERANCE,
    Claim,
    Result,
    Status,
    in_range,
    is_empty,
    money,
    parse_iso_date,
    to_decimal,
)
from claimguard.edu.policy import RuleContext

#: Missing values that are an observed defect under R001 (docs/04_Rulebook.md:42).
REQUIRED_CLAIM_FIELDS: Final = ("invoice_number", "member_id", "diagnosis_code")
REQUIRED_LINE_FIELDS: Final = (
    "service_date",
    "service_code",
    "quantity",
    "unit_price",
    "net_amount",
)
#: The duplicate key triple of R006 (docs/04_Rulebook.md:82).
DUPLICATE_KEY_FIELDS: Final = ("service_code", "service_date", "modifier")

#: R007's abstention reason, used both when the rule abstains and when it reports
#: FAIL while another line's arithmetic input is missing (docs/04_Rulebook.md:10).
ARITHMETIC_INPUT_MISSING: Final = "Arithmetic input missing"


def r001(claim: Claim, ctx: RuleContext) -> Result:
    """R001 — required claim information (docs/04_Rulebook.md:40-46).

    A known absence is FAIL, not UNABLE_TO_ASSESS; the transport contract has
    already guaranteed the structural keys, the claim ID, a nonempty line array
    and unique line IDs, so only values are examined here.
    """
    meta = ctx.rule("R001")
    pointers: list[str] = [f"/{field}" for field in REQUIRED_CLAIM_FIELDS if is_empty(claim[field])]
    line_ids: list[str] = []
    for index, line in enumerate(claim["lines"]):
        for field in REQUIRED_LINE_FIELDS:
            if is_empty(line[field]):
                pointers.append(f"/lines/{index}/{field}")
                line_ids.append(line["line_id"])
    if pointers:
        return make_result(
            claim, meta, Status.FAIL, "Required information is missing.", pointers, line_ids
        )
    present = ["/invoice_number", "/member_id", "/diagnosis_code", "/lines"]
    return make_result(claim, meta, Status.PASS, "Required information is present.", present)


def r002(claim: Claim, ctx: RuleContext) -> Result:
    """R002 — service and submission chronology (docs/04_Rulebook.md:48-54).

    Every service date must be on or before the submission date; equality
    passes. Missing or invalid dates abstain unless another line proves a
    violation.
    """
    meta = ctx.rule("R002")
    lines = claim["lines"]
    submission = parse_iso_date(claim["submission_date"])
    pointers = ["/submission_date", *(f"/lines/{i}/service_date" for i in range(len(lines)))]
    findings: list[str] = []
    unknowns: list[str] = []
    line_ids: list[str] = []
    if submission is None:
        unknowns.append("Date unavailable")
    for line in lines:
        day = parse_iso_date(line["service_date"])
        if day is None:
            unknowns.append("Date unavailable")
            continue
        if submission is not None and day > submission:
            findings.append("Service occurs after submission")
            line_ids.append(line["line_id"])
    if findings:
        return make_result(
            claim,
            meta,
            Status.FAIL,
            format_findings_with_uncertainty(findings, unknowns),
            pointers,
            line_ids,
        )
    if unknowns:
        return make_result(
            claim, meta, Status.UNABLE_TO_ASSESS, format_findings(unknowns), pointers
        )
    return make_result(claim, meta, Status.PASS, SATISFIED, pointers)


def r003(claim: Claim, ctx: RuleContext) -> Result:
    """R003 — coverage active on the service date (docs/04_Rulebook.md:56-62).

    ``coverage.status`` must be ``active`` and every service date must fall in
    the inclusive coverage period. The period is interpreted against the service
    date, never today's date (docs/03_Data_Dictionary.md).
    """
    meta = ctx.rule("R003")
    coverage = claim["coverage"]
    lines = claim["lines"]
    pointers = [
        "/coverage/status",
        "/coverage/start_date",
        "/coverage/end_date",
        *(f"/lines/{i}/service_date" for i in range(len(lines))),
    ]
    status = coverage["status"]
    start = parse_iso_date(coverage["start_date"])
    end = parse_iso_date(coverage["end_date"])
    findings: list[str] = []
    unknowns: list[str] = []
    line_ids: list[str] = []
    if is_empty(status):
        unknowns.append("coverage status")
    elif status != "active":
        findings.append("coverage status is not active")
    if start is None or end is None:
        unknowns.append("coverage period")
    for line in lines:
        day = parse_iso_date(line["service_date"])
        if day is None:
            unknowns.append("service date")
            continue
        if not in_range(day, start, end):
            findings.append("service outside coverage period")
            line_ids.append(line["line_id"])
    if findings:
        # A proven violation gives FAIL, but the concurrent abstention reasons are
        # preserved in the explanation (docs/04_Rulebook.md:10). The wording mirrors
        # the mentor reference, which appends "Additional unknown inputs: ..."
        # (pack src/engine_core.py, R003).
        return make_result(
            claim,
            meta,
            Status.FAIL,
            format_findings_with_uncertainty(findings, unknowns),
            pointers,
            line_ids,
        )
    if unknowns:
        return make_result(
            claim, meta, Status.UNABLE_TO_ASSESS, format_findings(unknowns), pointers
        )
    return make_result(
        claim,
        meta,
        Status.PASS,
        "All service dates are within active coverage, including boundaries.",
        pointers,
    )


def r004(claim: Claim, ctx: RuleContext) -> Result:
    """R004 — member and beneficiary consistency (docs/04_Rulebook.md:64-70).

    Exact, case-sensitive identifier comparison; missing comparison inputs
    abstain rather than pass.
    """
    meta = ctx.rule("R004")
    coverage = claim["coverage"]
    pairs = (
        (claim["patient_id"], coverage["beneficiary_patient_id"]),
        (claim["member_id"], coverage["member_id"]),
    )
    pointers = [
        "/patient_id",
        "/coverage/beneficiary_patient_id",
        "/member_id",
        "/coverage/member_id",
    ]
    findings: list[str] = []
    unknowns: list[str] = []
    for claimed, recorded in pairs:
        if is_empty(claimed) or is_empty(recorded):
            unknowns.append("Identifier missing")
        elif claimed != recorded:
            findings.append("Patient or member identifier mismatch")
    if findings:
        return make_result(
            claim,
            meta,
            Status.FAIL,
            format_findings_with_uncertainty(findings, unknowns),
            pointers,
        )
    if unknowns:
        return make_result(
            claim, meta, Status.UNABLE_TO_ASSESS, format_findings(unknowns), pointers
        )
    return make_result(claim, meta, Status.PASS, SATISFIED, pointers)


def r005(claim: Claim, ctx: RuleContext) -> Result:
    """R005 — provider in the supplied network (docs/04_Rulebook.md:72-78).

    An unavailable policy or a missing provider abstains; the supplied network
    list is complete for this fictional challenge.
    """
    meta = ctx.rule("R005")
    pointers = ["/provider_id", "/policy_id"]
    policy = ctx.policy(claim["policy_id"])
    if policy is None:
        return make_result(
            claim,
            meta,
            Status.UNABLE_TO_ASSESS,
            "No policy is supplied for this policy_id.",
            pointers,
        )
    if is_empty(claim["provider_id"]):
        return make_result(claim, meta, Status.UNABLE_TO_ASSESS, "Identifier missing", pointers)
    if claim["provider_id"] not in policy.allowed_providers:
        return make_result(
            claim, meta, Status.FAIL, "Provider absent from supplied network", pointers
        )
    return make_result(claim, meta, Status.PASS, SATISFIED, pointers)


def r006(claim: Claim, ctx: RuleContext) -> Result:
    """R006 — possible duplicate service lines (docs/04_Rulebook.md:80-86).

    The key is ``(service_code, service_date, modifier)`` with a null modifier
    normalised to an empty string. Different modifiers or dates are not
    duplicates here. FAIL means a possible duplicate for human review, not fraud.
    """
    meta = ctx.rule("R006")
    seen: dict[tuple[Any, Any, Any], int] = {}
    duplicated: list[int] = []
    incomplete = False
    for index, line in enumerate(claim["lines"]):
        if is_empty(line["service_code"]) or parse_iso_date(line["service_date"]) is None:
            incomplete = True
            continue
        key = (line["service_code"], line["service_date"], line["modifier"] or "")
        if key in seen:
            duplicated.extend((seen[key], index))
        else:
            seen[key] = index
    indices = sorted(set(duplicated))
    if indices:
        pointers = [
            f"/lines/{index}/{field}" for index in indices for field in DUPLICATE_KEY_FIELDS
        ]
        line_ids = [claim["lines"][index]["line_id"] for index in indices]
        # Preserve the concurrent uncertainty even though a duplicate was proven
        # (docs/04_Rulebook.md:10); wording mirrors the mentor reference
        # (pack src/engine_core.py, R006).
        message = "Possible duplicate lines require review."
        if incomplete:
            message += " Additional lines have missing inputs."
        return make_result(claim, meta, Status.FAIL, message, pointers, line_ids)
    if incomplete:
        return make_result(
            claim,
            meta,
            Status.UNABLE_TO_ASSESS,
            "Missing inputs prevent a complete duplicate check.",
            ["/lines"],
        )
    return make_result(
        claim, meta, Status.PASS, "No duplicate service/date/modifier combinations.", ["/lines"]
    )


def r007(claim: Claim, ctx: RuleContext) -> Result:
    """R007 — line arithmetic (docs/04_Rulebook.md:88-94).

    ``net_amount`` must equal ``quantity * unit_price`` rounded to 2 decimals
    with ROUND_HALF_UP; a difference of at most 0.01 SAR passes. Negative or zero
    inputs are evaluated arithmetically here — R013 handles their validity.
    """
    meta = ctx.rule("R007")
    pointers: list[str] = []
    findings: list[str] = []
    incomplete = False
    line_ids: list[str] = []
    for index, line in enumerate(claim["lines"]):
        if (
            is_empty(line["quantity"])
            or is_empty(line["unit_price"])
            or is_empty(line["net_amount"])
        ):
            incomplete = True
            continue
        pointers.extend(
            (
                f"/lines/{index}/quantity",
                f"/lines/{index}/unit_price",
                f"/lines/{index}/net_amount",
            )
        )
        expected = money(to_decimal(line["quantity"]) * to_decimal(line["unit_price"]))
        if abs(to_decimal(line["net_amount"]) - expected) > MONEY_TOLERANCE:
            findings.append("Line amount differs from quantity times price")
            line_ids.append(line["line_id"])
    if findings:
        return make_result(
            claim,
            meta,
            Status.FAIL,
            format_findings_with_uncertainty(
                findings, [ARITHMETIC_INPUT_MISSING] if incomplete else []
            ),
            pointers or ["/lines"],
            line_ids,
        )
    if incomplete:
        return make_result(
            claim,
            meta,
            Status.UNABLE_TO_ASSESS,
            ARITHMETIC_INPUT_MISSING,
            pointers or ["/lines"],
        )
    return make_result(claim, meta, Status.PASS, SATISFIED, pointers or ["/lines"])
