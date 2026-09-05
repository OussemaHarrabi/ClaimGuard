"""FHIR parser tests, anchored on the CLM-0042 flagship fixture.

CLM-0042 (Velodoc's published fixture): Sara Mansour, MRI lumbar spine,
NorthStar Medical Center, payer HealthPlus Gold, service 2026-08-20,
coverage ended 2026-08-15, no authorization, two identical 1800 AED MRI lines.

Its three defects MUST survive parsing, or the whole downstream system is
validating a fixture that has nothing wrong with it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from claimguard.ingest.fhir import parse_bundle


def _flagship_bundle() -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "fullUrl": "urn:uuid:claim-0042",
                "resource": {
                    "resourceType": "Claim",
                    "id": "CLM-0042",
                    "status": "active",
                    "type": {"coding": [{"code": "institutional"}]},
                    "use": "claim",
                    "created": "2026-08-20T09:00:00Z",
                    "patient": {"reference": "Patient/MBR-001"},
                    "provider": {"reference": "Organization/PRV-7731"},
                    "insurance": [
                        {
                            "sequence": 1,
                            "focal": True,
                            "coverage": {"reference": "Coverage/COV-7711"},
                        }
                    ],
                    "item": [
                        {
                            "sequence": 1,
                            "productOrService": {"coding": [{"code": "72148"}]},
                            "servicedDate": "2026-08-20",
                            "quantity": {"value": 1},
                            "net": {"value": 1800, "currency": "AED"},
                            "encounter": [{"reference": "Encounter/ENC-9002"}],
                        },
                        {
                            "sequence": 2,
                            "productOrService": {"coding": [{"code": "72148"}]},
                            "servicedDate": "2026-08-20",
                            "quantity": {"value": 1},
                            "net": {"value": 1800, "currency": "AED"},
                            "encounter": [{"reference": "Encounter/ENC-9002"}],
                        },
                    ],
                    "total": {"value": 3600, "currency": "AED"},
                },
            },
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "MBR-001",
                    "identifier": [{"value": "SUB-001"}],
                    "name": [{"family": "Mansour", "given": ["Sara"]}],
                    "birthDate": "1992-03-14",
                    "gender": "female",
                }
            },
            {
                "resource": {
                    "resourceType": "Organization",
                    "id": "PRV-7731",
                    "name": "NorthStar Medical Center",
                    "identifier": [{"value": "PRV-7731"}],
                    "type": [{"coding": [{"code": "prov"}]}],
                }
            },
            {
                "resource": {
                    "resourceType": "Coverage",
                    "id": "COV-7711",
                    "status": "active",
                    "subscriberId": "SUB-001",
                    "period": {"start": "2025-09-01", "end": "2026-08-15"},
                    "payor": [{"reference": "Organization/PAY-001"}],
                    "class": [{"name": "Gold"}],
                }
            },
            {
                "resource": {
                    "resourceType": "Organization",
                    "id": "PAY-001",
                    "name": "HealthPlus Gold",
                }
            },
            {
                "resource": {
                    "resourceType": "Encounter",
                    "id": "ENC-9002",
                    "status": "finished",
                    "subject": {"reference": "Patient/MBR-001"},
                }
            },
        ],
    }


# ---------------------------------------------------------------------------
# Header + parties
# ---------------------------------------------------------------------------


def test_flagship_header_parses() -> None:
    claim = parse_bundle(_flagship_bundle())
    assert claim.claim_id == "CLM-0042"
    assert claim.status == "active"
    assert claim.use == "claim"
    assert claim.envelope_errors == [], f"flagship should be well-formed: {claim.envelope_errors}"


def test_patient_resolved() -> None:
    claim = parse_bundle(_flagship_bundle())
    assert claim.patient is not None
    assert claim.patient.name == "Sara Mansour"
    assert claim.patient.member_id == "MBR-001"
    assert claim.patient.subscriber_id == "SUB-001"


def test_provider_resolved() -> None:
    claim = parse_bundle(_flagship_bundle())
    assert claim.provider is not None
    assert claim.provider.name == "NorthStar Medical Center"
    assert claim.provider.provider_id == "PRV-7731"


def test_focal_coverage_resolved_with_payer() -> None:
    claim = parse_bundle(_flagship_bundle())
    assert claim.coverage is not None
    assert claim.coverage.payer_name == "HealthPlus Gold"
    assert claim.coverage.plan_name == "Gold"


# ---------------------------------------------------------------------------
# THE THREE DEFECTS MUST SURVIVE PARSING
# ---------------------------------------------------------------------------


def test_defect_1_coverage_ended_before_service() -> None:
    """COV-001: coverage ended 2026-08-15, service 2026-08-20."""
    claim = parse_bundle(_flagship_bundle())
    assert claim.coverage is not None
    assert claim.coverage.period_end is not None
    assert claim.anchor_date is not None
    assert claim.anchor_date > claim.coverage.period_end


def test_defect_2_no_authorization() -> None:
    """AUTH-004: no preAuthRef anywhere in the package."""
    claim = parse_bundle(_flagship_bundle())
    assert claim.authorization is None


def test_defect_3_duplicate_lines() -> None:
    """DUP-002: two identical service lines."""
    claim = parse_bundle(_flagship_bundle())
    assert len(claim.lines) == 2
    a, b = claim.lines[0], claim.lines[1]
    assert a.product_or_service == b.product_or_service == "72148"
    assert a.serviced_date == b.serviced_date
    assert a.net is not None and b.net is not None
    assert a.net.value == b.net.value == Decimal("1800")


# ---------------------------------------------------------------------------
# Lines, money, encounter
# ---------------------------------------------------------------------------


def test_lines_have_money_and_sequence() -> None:
    claim = parse_bundle(_flagship_bundle())
    assert claim.lines[0].sequence == 1
    assert claim.lines[1].sequence == 2
    assert claim.lines[0].net is not None
    assert claim.lines[0].net.currency == "AED"


def test_encounter_resolves_and_matches_member() -> None:
    claim = parse_bundle(_flagship_bundle())
    assert claim.encounter is not None
    assert claim.encounter.encounter_id == "ENC-9002"
    assert claim.encounter.subject_resolved is True
    assert claim.encounter.subject_matches_member is True


def test_total_parsed() -> None:
    claim = parse_bundle(_flagship_bundle())
    assert claim.total is not None
    assert claim.total.value == Decimal("3600")


# ---------------------------------------------------------------------------
# Malformed input must never raise
# ---------------------------------------------------------------------------


def test_empty_bundle_yields_envelope_error() -> None:
    claim = parse_bundle({})
    assert claim.envelope_errors
    assert claim.claim_id is None
    assert claim.lines == []


def test_bundle_without_claim_yields_error() -> None:
    claim = parse_bundle(
        {"resourceType": "Bundle", "entry": [{"resource": {"resourceType": "Patient", "id": "1"}}]}
    )
    assert claim.envelope_errors


def test_claim_missing_required_fields_is_reported_not_raised() -> None:
    claim = parse_bundle({"resourceType": "Claim", "status": "active"})
    assert claim.envelope_errors
    # ID-less and line-less at minimum
    assert any("id" in e for e in claim.envelope_errors)
    assert any("service lines" in e for e in claim.envelope_errors)


def test_unresolvable_references_do_not_raise() -> None:
    bundle = {
        "resourceType": "Claim",
        "id": "CLM-X",
        "patient": {"reference": "Patient/GHOST"},
        "provider": {"reference": "Organization/GHOST"},
        "item": [
            {
                "sequence": 1,
                "productOrService": {"coding": [{"code": "72148"}]},
                "servicedDate": "2026-08-20",
                "encounter": [{"reference": "Encounter/GHOST"}],
            }
        ],
    }
    claim = parse_bundle(bundle)
    assert claim.patient is None
    assert claim.provider is None
    assert claim.encounter is None
    assert claim.envelope_errors


def test_garbage_types_do_not_raise() -> None:
    claim = parse_bundle({"resourceType": "Claim", "id": "X", "item": "not-a-list", "total": 5})
    assert claim.lines == []
    assert claim.total is None
