"""The P0-1 guard — this test exists so a catastrophic bug cannot return silently.

BACKGROUND (see 09 §Part B, P0-1)
---------------------------------
The rule engine evaluates CEL expressions authored in camelCase, e.g.:

    payload.coverage.periodEnd != "" && payload.anchorDate > payload.coverage.periodEnd

An earlier version of `to_rule_payload()` called `model_dump(by_alias=False)`,
which emits snake_case keys (`coverage.period_end`). Every CEL condition then read
`None` and evaluated false. The engine reported "no findings" — on claims that
definitely had findings. It failed silently and looked like success.

A system whose rules never fire is worse than one that crashes, because it ships.

WHAT THESE TESTS GUARANTEE
--------------------------
1. The canonical model emits camelCase keys (the alias contract holds).
2. A realistic claim round-trips every field a rule needs, under the exact dotted
   paths the CEL catalogue uses.
3. Nested objects survive serialization intact — specifically that `coverage`
   retains `periodEnd` and `patient` retains `memberId` (the P0-2 overwrite bug).
4. Any CEL expression in the catalogue only references resolvable paths.

If someone removes an alias, renames a field, or reintroduces an `env`-style
partial merge, these tests fail in CI.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import cast

import pytest
from claimguard.canonical import (
    Attachment,
    CanonicalClaim,
    ClaimLine,
    Coverage,
    Encounter,
    Member,
    Money,
    Provider,
)
from pydantic import ValidationError

# Paths that CEL conditions actually reference (05 §5.2, 03 §2.4).
# Keep this list in sync with the rule catalogue — it is the contract.
CEL_REFERENCED_PATHS = [
    "claimId",
    "status",
    "coverage.periodEnd",
    "coverage.periodStart",
    "coverage.payerName",
    "coverage.planName",
    "authorization.reference",
    "authorization.validFrom",
    "authorization.validTo",
    "authorization.procedureCode",
    "patient.memberId",
    "provider.providerId",
    "lines.0.productOrService",
    "lines.0.servicedDate",
    "lines.0.servicedPeriodStart",
    "lines.0.servicedPeriodEnd",
    "lines.0.net.value",
    "lines.0.quantity",
    "lines.0.encounterRefsResolved",
    "benefitBalance.remaining",
]


def _flagship_claim() -> CanonicalClaim:
    """CLM-0042 — the flagship fixture (Sara Mansour).

    Coverage ended 2026-08-15, service 2026-08-20, no authorization,
    two identical MRI lines at 1800 each.
    """
    return CanonicalClaim(
        claim_id="CLM-0042",
        status="active",
        type="institutional",
        use="claim",
        currency="AED",
        patient=Member(
            member_id="MBR-001",
            subscriber_id="SUB-001",
            name="Sara Mansour",
            date_of_birth=date(1992, 3, 14),
        ),
        provider=Provider(
            provider_id="PRV-7731", name="NorthStar Medical Center", type="institutional"
        ),
        coverage=Coverage(
            coverage_id="COV-7711",
            status="active",
            payer_name="HealthPlus Gold",
            plan_name="Gold",
            period_start=date(2025, 9, 1),
            period_end=date(2026, 8, 15),  # ENDED before service
        ),
        authorization=None,  # AUTH-004: missing
        encounter=Encounter(encounter_id="ENC-9002", status="finished"),
        attachments=[Attachment(reference="DOC-1", ref_resolved=False, content_present=False)],
        lines=[
            ClaimLine(
                sequence=1,
                product_or_service="72148",  # MRI lumbar spine
                serviced_date=date(2026, 8, 20),
                quantity=Decimal("1"),
                net=Money(value=Decimal("1800")),
            ),
            ClaimLine(
                sequence=2,
                product_or_service="72148",  # DUP-002: identical line
                serviced_date=date(2026, 8, 20),
                quantity=Decimal("1"),
                net=Money(value=Decimal("1800")),
            ),
        ],
    )


def _resolve(payload: object, dotted: str) -> tuple[bool, object]:
    """Walk a dotted path; return (resolved, value)."""
    cur: object = payload
    for part in dotted.split("."):
        if isinstance(cur, dict):
            d = cast(dict[str, object], cur)
            if part not in d:
                return False, None
            cur = d[part]
        elif isinstance(cur, list):
            try:
                cur = cast(list[object], cur)[int(part)]
            except (IndexError, ValueError):
                return False, None
        else:
            return False, None
    return True, cur


# ---------------------------------------------------------------------------
# 1. The alias contract
# ---------------------------------------------------------------------------


def test_payload_uses_camelcase_aliases() -> None:
    """model_dump must emit camelCase, not snake_case."""
    payload = _flagship_claim().to_rule_payload()

    assert "claim_id" not in payload, "snake_case leaked — aliases are missing (P0-1 regression)"
    assert "claimId" in payload
    assert "coverage" in payload
    assert "periodEnd" in payload["coverage"], "coverage.periodEnd missing — COV-001 cannot fire"


def test_no_snake_case_keys_anywhere() -> None:
    """No underscore-style keys at any depth. Cheap, exhaustive guard."""
    payload = _flagship_claim().to_rule_payload()

    def walk(node: object, path: str = "") -> list[str]:
        bad: list[str] = []
        if isinstance(node, dict):
            d = cast(dict[str, object], node)
            for key, value in d.items():
                if "_" in str(key):
                    bad.append(f"{path}.{key}" if path else str(key))
                bad.extend(walk(value, f"{path}.{key}" if path else str(key)))
        elif isinstance(node, list):
            lst = cast(list[object], node)
            for i, value in enumerate(lst):
                bad.extend(walk(value, f"{path}.{i}" if path else str(i)))
        return bad

    offenders = walk(payload)
    assert not offenders, f"snake_case keys in rule payload (P0-1 regression): {offenders}"


# ---------------------------------------------------------------------------
# 2. Every CEL-referenced path resolves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dotted", CEL_REFERENCED_PATHS)
def test_cel_referenced_paths_resolve(dotted: str) -> None:
    """Each path a rule actually uses must resolve on a realistic claim."""
    payload = _flagship_claim().to_rule_payload()
    resolved, _ = _resolve(payload, dotted)
    assert resolved, f"CEL path '{dotted}' does not resolve in the rule payload"


# ---------------------------------------------------------------------------
# 3. P0-2 — nested objects must survive intact
# ---------------------------------------------------------------------------


def test_coverage_retains_nested_fields_after_dump() -> None:
    """The P0-2 regression: a flat partial dict must never overwrite coverage."""
    payload = _flagship_claim().to_rule_payload()

    coverage = payload["coverage"]
    assert coverage["periodEnd"] == "2026-08-15"
    assert coverage["periodStart"] == "2025-09-01"
    assert coverage["payerName"] == "HealthPlus Gold"
    assert coverage["planName"] == "Gold"
    assert set(coverage) >= {"periodEnd", "periodStart", "payerName", "planName"}, (
        "coverage lost nested fields — check for an env-style partial merge (P0-2)"
    )


def test_patient_retains_nested_fields() -> None:
    payload = _flagship_claim().to_rule_payload()
    patient = payload["patient"]

    assert patient["memberId"] == "MBR-001"
    assert patient["name"] == "Sara Mansour"
    assert "dateOfBirth" in patient


def test_absent_authorization_is_navigable_but_empty() -> None:
    """The density contract: an absent authorization is a null-filled object.

    It must be NAVIGABLE (so `payload.authorization.validFrom` does not error and
    AUTH-006 can evaluate) while all its fields are null (so AUTH-004 can see
    there is no reference). This is what makes a missing authorization
    detectable rather than invisible.
    """
    payload = _flagship_claim().to_rule_payload()

    auth = payload["authorization"]
    assert isinstance(auth, dict), "absent nested model must densify to an object, not null"
    assert auth["reference"] is None
    assert auth["validFrom"] is None
    assert auth["validTo"] is None

    # And densification must not have disturbed siblings (the P0-2 protection).
    assert payload["coverage"]["periodEnd"] == "2026-08-15"
    assert payload["patient"]["memberId"] == "MBR-001"


# 4. Derived anchor date
# ---------------------------------------------------------------------------


def test_anchor_date_is_earliest_service_date() -> None:
    claim = _flagship_claim()
    assert claim.anchor_date == date(2026, 8, 20)
    assert claim.to_rule_payload()["anchorDate"] == "2026-08-20"


def test_anchor_date_none_without_lines() -> None:
    claim = CanonicalClaim(claim_id="CLM-EMPTY", lines=[])
    assert claim.anchor_date is None
    assert claim.to_rule_payload()["anchorDate"] is None


# ---------------------------------------------------------------------------
# 5. The flagship is genuinely broken (sanity: our fixture has real defects)
# ---------------------------------------------------------------------------


def test_flagship_has_the_three_expected_defects() -> None:
    """If this fails, our fixture is wrong — not the engine.

    CLM-0042 must exhibit: coverage ended before service, missing authorization,
    duplicate line. Without all three, the E2E test (EVL-09) proves nothing.
    """
    claim = _flagship_claim()

    # COV-001: coverage ended 2026-08-15, service 2026-08-20
    assert claim.coverage is not None
    assert claim.coverage.period_end is not None
    assert claim.anchor_date is not None
    assert claim.anchor_date > claim.coverage.period_end

    # AUTH-004: no authorization
    assert claim.authorization is None or not claim.authorization.reference

    # DUP-002: two identical lines
    assert len(claim.lines) == 2
    assert claim.lines[0].product_or_service == claim.lines[1].product_or_service
    assert claim.lines[0].serviced_date == claim.lines[1].serviced_date


def test_extra_fields_are_rejected() -> None:
    """Typo safety: an unknown field must raise, not pass silently."""
    with pytest.raises(ValidationError):
        CanonicalClaim(claim_id="X", claimIdTypo="Y")  # type: ignore[call-arg]
