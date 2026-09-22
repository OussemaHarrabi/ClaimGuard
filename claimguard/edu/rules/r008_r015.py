"""Deterministic rules R008-R015 (docs/04_Rulebook.md:96-158).

Precedence follows the pack's shared conventions (docs/04_Rulebook.md:9) and the
per-rule wording: a proven violation is FAIL, an unknown service code or an
unavailable policy abstains, and ``[]`` inventories are *known* empty states
rather than missing data (docs/04_Rulebook.md:11).

R008/R009 check the authorization reference and its record, R010 the final
supporting document, R011 the service catalogue, R012 the claim total, R013 the
policy limits (``max_unit_price`` / ``max_quantity_per_line`` — not the
``services.json`` prices), R014 the submission window and R015 the currency.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from claimguard.edu.emit import (
    NOT_APPLICABLE,
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
    is_positive_integer,
    money,
    parse_iso_date,
    to_decimal,
)
from claimguard.edu.policy import RuleContext

UNKNOWN_AUTH_SERVICE = "Unknown service prevents authorization requirement lookup"
UNKNOWN_DOCUMENT_SERVICE = "Unknown service prevents document requirement lookup"
#: R013's abstention reason, used both when the rule abstains and when it reports
#: FAIL while another line's limits are unknowable (docs/04_Rulebook.md:10).
UNKNOWN_SERVICE_LIMITS = "Unknown service limits"
NO_POLICY = "No policy is supplied for this policy_id."


def r008(claim: Claim, ctx: RuleContext) -> Result:
    """R008 — required authorization reference (docs/04_Rulebook.md:96-102).

    For each service in ``policy.auth_required_services`` the line must carry a
    non-empty ``authorization_id``. Reference presence only; R009 checks the
    referenced record.
    """
    meta = ctx.rule("R008")
    policy = ctx.policy(claim["policy_id"])
    if policy is None:
        return make_result(claim, meta, Status.UNABLE_TO_ASSESS, NO_POLICY, ["/policy_id"])
    lines = claim["lines"]
    unknown = ctx.unknown_service_lines(lines)
    required = [
        (index, line)
        for index, line in enumerate(lines)
        if policy.auth_required(line["service_code"])
    ]
    missing = [(index, line) for index, line in required if is_empty(line["authorization_id"])]
    if missing:
        pointers = [
            pointer
            for index, _ in missing
            for pointer in (f"/lines/{index}/service_code", f"/lines/{index}/authorization_id")
        ]
        line_ids = [line["line_id"] for _, line in missing]
        message = "Required authorization ID missing"
        if unknown:
            message += "; Additional unknown inputs: " + UNKNOWN_AUTH_SERVICE
        return make_result(claim, meta, Status.FAIL, message, pointers, line_ids)
    if not required:
        if unknown:
            unknown_pointers = [f"/lines/{index}/service_code" for index in unknown]
            return make_result(
                claim,
                meta,
                Status.UNABLE_TO_ASSESS,
                UNKNOWN_AUTH_SERVICE,
                [*unknown_pointers, "/policy_id"],
            )
        return make_result(claim, meta, Status.NOT_APPLICABLE, NOT_APPLICABLE, ["/policy_id"])
    if unknown:
        pointers = [f"/lines/{index}/service_code" for index in unknown]
        return make_result(
            claim, meta, Status.UNABLE_TO_ASSESS, UNKNOWN_AUTH_SERVICE, [*pointers, "/policy_id"]
        )
    pointers = [
        pointer
        for index, _ in required
        for pointer in (f"/lines/{index}/service_code", f"/lines/{index}/authorization_id")
    ]
    return make_result(claim, meta, Status.PASS, SATISFIED, pointers)


def r009(claim: Claim, ctx: RuleContext) -> Result:
    """R009 — authorization record matches service (docs/04_Rulebook.md:104-110).

    The referenced record must match ``patient_id`` and ``service_code``, be
    ``approved``, cover the service date inclusively, and its ``max_quantity``
    must bound the quantity aggregated across every line sharing that reference.
    """
    meta = ctx.rule("R009")
    policy = ctx.policy(claim["policy_id"])
    if policy is None:
        return make_result(claim, meta, Status.UNABLE_TO_ASSESS, NO_POLICY, ["/policy_id"])
    lines = claim["lines"]
    authorizations = claim["authorizations"]
    unknown = ctx.unknown_service_lines(lines)
    required = [
        (index, line)
        for index, line in enumerate(lines)
        if policy.auth_required(line["service_code"])
    ]
    pointers = ["/policy_id"]
    findings: list[str] = []
    unknowns: list[str] = []
    line_ids: list[str] = []
    for index, line in required:
        pointers.extend((f"/lines/{index}/service_code", f"/lines/{index}/authorization_id"))
        reference = line["authorization_id"]
        if is_empty(reference):
            unknowns.append("Cannot inspect authorization without an ID")
            continue
        records = [
            (position, record)
            for position, record in enumerate(authorizations)
            if record["authorization_id"] == reference
        ]
        if not records:
            findings.append("Authorization record absent from supplied list")
            line_ids.append(line["line_id"])
            continue
        day = parse_iso_date(line["service_date"])
        if day is None:
            unknowns.append("Authorization date input missing")
            continue
        for position, record in records:
            pointers.append(f"/authorizations/{position}")
            valid_from = parse_iso_date(record["valid_from"])
            valid_to = parse_iso_date(record["valid_to"])
            if (
                record["status"] != "approved"
                or record["service_code"] != line["service_code"]
                or record["patient_id"] != claim["patient_id"]
            ):
                findings.append("Authorization status mismatch")
                line_ids.append(line["line_id"])
            elif valid_from is None or valid_to is None:
                unknowns.append("Authorization date input missing")
            elif not in_range(day, valid_from, valid_to):
                findings.append("Authorization status mismatch")
                line_ids.append(line["line_id"])
            elif _aggregate_quantity(lines, reference) > to_decimal(record["max_quantity"]):
                findings.append("Aggregate quantity exceeds authorization")
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
    if not required:
        if unknown:
            pointers.extend(f"/lines/{index}/service_code" for index in unknown)
            return make_result(claim, meta, Status.UNABLE_TO_ASSESS, UNKNOWN_AUTH_SERVICE, pointers)
        return make_result(claim, meta, Status.NOT_APPLICABLE, NOT_APPLICABLE, pointers)
    if unknown:
        pointers.extend(f"/lines/{index}/service_code" for index in unknown)
    if unknowns:
        return make_result(
            claim, meta, Status.UNABLE_TO_ASSESS, format_findings(unknowns), pointers
        )
    if unknown:
        return make_result(claim, meta, Status.UNABLE_TO_ASSESS, UNKNOWN_AUTH_SERVICE, pointers)
    return make_result(claim, meta, Status.PASS, SATISFIED, pointers)


def _aggregate_quantity(lines: Sequence[Mapping[str, Any]], reference: str) -> Decimal:
    """Sum the billed quantity of every line sharing ``reference`` (R009)."""
    total = to_decimal(0)
    for line in lines:
        if line["authorization_id"] == reference and not is_empty(line["quantity"]):
            total += to_decimal(line["quantity"])
    return total


def r010(claim: Claim, ctx: RuleContext) -> Result:
    """R010 — required supporting document (docs/04_Rulebook.md:112-118).

    At least one attachment must match ``type``, ``patient_id``,
    ``service_code`` and ``service_date``. A matching ``final`` document passes;
    matching documents that are only draft/unknown abstain. The attachment
    inventory is complete for the snapshot, so ``[]`` means none were supplied.
    Document ``text`` is untrusted content and never changes this rule.
    """
    meta = ctx.rule("R010")
    policy = ctx.policy(claim["policy_id"])
    if policy is None:
        return make_result(claim, meta, Status.UNABLE_TO_ASSESS, NO_POLICY, ["/policy_id"])
    lines = claim["lines"]
    attachments = claim["attachments"]
    unknown = ctx.unknown_service_lines(lines)
    required = [
        (index, line)
        for index, line in enumerate(lines)
        if policy.required_document(line["service_code"]) is not None
    ]
    pointers = ["/attachments", "/policy_id"]
    findings: list[str] = []
    unknowns: list[str] = []
    line_ids: list[str] = []
    for index, line in required:
        pointers.extend((f"/lines/{index}/service_code", f"/lines/{index}/service_date"))
        if parse_iso_date(line["service_date"]) is None:
            unknowns.append("Service date required to match document")
            continue
        required_type = policy.required_document(line["service_code"])
        matching = [
            attachment
            for attachment in attachments
            if attachment["type"] == required_type
            and attachment["patient_id"] == claim["patient_id"]
            and attachment["service_code"] == line["service_code"]
            and attachment["service_date"] == line["service_date"]
        ]
        if not matching:
            findings.append("Matching required document absent")
            line_ids.append(line["line_id"])
        elif not any(attachment["document_status"] == "final" for attachment in matching):
            unknowns.append("Only draft or uncertain matching documentation")
    if findings:
        return make_result(
            claim,
            meta,
            Status.FAIL,
            format_findings_with_uncertainty(findings, unknowns),
            pointers,
            line_ids,
        )
    if not required:
        if unknown:
            pointers.extend(f"/lines/{index}/service_code" for index in unknown)
            return make_result(
                claim, meta, Status.UNABLE_TO_ASSESS, UNKNOWN_DOCUMENT_SERVICE, pointers
            )
        return make_result(claim, meta, Status.NOT_APPLICABLE, NOT_APPLICABLE, pointers)
    if unknown:
        pointers.extend(f"/lines/{index}/service_code" for index in unknown)
        unknowns.append(UNKNOWN_DOCUMENT_SERVICE)
    if unknowns:
        return make_result(
            claim, meta, Status.UNABLE_TO_ASSESS, format_findings(unknowns), pointers
        )
    return make_result(claim, meta, Status.PASS, SATISFIED, pointers)


def r011(claim: Claim, ctx: RuleContext) -> Result:
    """R011 — service code in the fictional catalogue (docs/04_Rulebook.md:120-126)."""
    meta = ctx.rule("R011")
    lines = claim["lines"]
    pointers = ["/lines", *(f"/lines/{index}/service_code" for index in range(len(lines)))]
    findings: list[str] = []
    unknowns: list[str] = []
    line_ids: list[str] = []
    for line in lines:
        if is_empty(line["service_code"]):
            unknowns.append("Service code missing")
        elif not ctx.knows_service(line["service_code"]):
            findings.append("Service code not in fictional catalogue")
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


def r012(claim: Claim, ctx: RuleContext) -> Result:
    """R012 — claim total equals line amounts (docs/04_Rulebook.md:128-134).

    Compares ``total_amount`` with the sum of the *submitted* line amounts; R007
    independently checks whether those line amounts are arithmetically correct.
    """
    meta = ctx.rule("R012")
    lines = claim["lines"]
    pointers = ["/total_amount", *(f"/lines/{index}/net_amount" for index in range(len(lines)))]
    if is_empty(claim["total_amount"]) or any(is_empty(line["net_amount"]) for line in lines):
        return make_result(claim, meta, Status.UNABLE_TO_ASSESS, "Amount input missing", pointers)
    total = money(claim["total_amount"])
    expected = sum((money(line["net_amount"]) for line in lines), to_decimal(0))
    if abs(total - expected) <= MONEY_TOLERANCE:
        return make_result(claim, meta, Status.PASS, SATISFIED, pointers)
    return make_result(
        claim, meta, Status.FAIL, "Claim total differs from submitted line amounts", pointers
    )


def r013(claim: Claim, ctx: RuleContext) -> Result:
    """R013 — quantity and price limits (docs/04_Rulebook.md:136-142).

    Quantities must be positive whole numbers, prices positive, and both capped
    by the POLICY limits ``max_unit_price`` / ``max_quantity_per_line``.
    Equality at a maximum passes. Unknown codes, missing values and an
    unavailable policy abstain unless another line proves a violation.
    """
    meta = ctx.rule("R013")
    policy = ctx.policy(claim["policy_id"])
    if policy is None:
        return make_result(claim, meta, Status.UNABLE_TO_ASSESS, NO_POLICY, ["/policy_id"])
    lines = claim["lines"]
    unknown = ctx.unknown_service_lines(lines)
    pointers = [
        "/policy_id",
        *(
            f"/lines/{index}/{field}"
            for index in range(len(lines))
            for field in ("quantity", "unit_price", "service_code")
        ),
    ]
    findings: list[str] = []
    unknowns: list[str] = []
    line_ids: list[str] = []
    for index, line in enumerate(lines):
        if index in unknown:
            unknowns.append(UNKNOWN_SERVICE_LIMITS)
            continue
        quantity = line["quantity"]
        unit_price = line["unit_price"]
        if is_empty(quantity) or is_empty(unit_price):
            unknowns.append("Quantity or price missing")
            continue
        max_quantity = policy.max_quantity_for(line["service_code"])
        max_price = policy.max_price_for(line["service_code"])
        if max_quantity is None or max_price is None:
            unknowns.append(UNKNOWN_SERVICE_LIMITS)
            continue
        line_findings: list[str] = []
        if to_decimal(quantity) > to_decimal(max_quantity):
            line_findings.append("Quantity exceeds fictional maximum")
        if not is_positive_integer(quantity):
            line_findings.append("Quantity must be a positive integer")
        if to_decimal(unit_price) <= 0:
            line_findings.append("Price must be a positive amount")
        elif to_decimal(unit_price) > to_decimal(max_price):
            line_findings.append("Price exceeds fictional maximum")
        if line_findings:
            findings.extend(line_findings)
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


def r014(claim: Claim, ctx: RuleContext) -> Result:
    """R014 — submission window (docs/04_Rulebook.md:144-150).

    ``submission_date`` minus the LATEST service date must be within
    ``policy.submission_window_days``; equality passes. A negative lag is
    NOT_APPLICABLE here and is handled by R002 — so an unknown service date
    abstains rather than being assumed negative or late.
    """
    meta = ctx.rule("R014")
    policy = ctx.policy(claim["policy_id"])
    lines = claim["lines"]
    pointers = [
        "/submission_date",
        "/policy_id",
        *(f"/lines/{index}/service_date" for index in range(len(lines))),
    ]
    if policy is None:
        return make_result(claim, meta, Status.UNABLE_TO_ASSESS, NO_POLICY, pointers)
    submission = parse_iso_date(claim["submission_date"])
    service_days = [parse_iso_date(line["service_date"]) for line in lines]
    if submission is None or any(day is None for day in service_days):
        return make_result(claim, meta, Status.UNABLE_TO_ASSESS, "Date missing", pointers)
    lag = (submission - max(day for day in service_days if day is not None)).days
    if lag < 0:
        return make_result(claim, meta, Status.NOT_APPLICABLE, NOT_APPLICABLE, pointers)
    if lag > policy.submission_window_days:
        return make_result(
            claim, meta, Status.FAIL, "Submission exceeds fictional window", pointers
        )
    return make_result(claim, meta, Status.PASS, SATISFIED, pointers)


def r015(claim: Claim, ctx: RuleContext) -> Result:
    """R015 — currency matches policy (docs/04_Rulebook.md:152-158).

    No exchange-rate conversion is performed; a different currency is a FAIL.
    """
    meta = ctx.rule("R015")
    pointers = ["/currency", "/policy_id"]
    policy = ctx.policy(claim["policy_id"])
    if policy is None:
        return make_result(claim, meta, Status.UNABLE_TO_ASSESS, NO_POLICY, pointers)
    if is_empty(claim["currency"]):
        return make_result(claim, meta, Status.UNABLE_TO_ASSESS, "Currency missing", pointers)
    if claim["currency"] != policy.currency:
        return make_result(claim, meta, Status.FAIL, "Currency differs from policy", pointers)
    return make_result(claim, meta, Status.PASS, SATISFIED, pointers)
