"""FHIR intake: the projection recovers what the bundle carries, and says what it cannot.

docs/11_FHIR_Orientation.md states the limits outright — "Full authorization
details, policy limits, notes and some source metadata remain in the normalized
sidecar; FHIR files alone are insufficient to reproduce all 15 checks" — and this
module is judged on being *exactly* as capable as that sentence allows: every
field it claims is checked against the authoritative envelope for all 600 public
bundles, every field it refuses is checked to be absent from the projection, and
the two sets are checked to partition the 17-key contract with nothing left over.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from claimguard.edu.envelope import (
    ATTACHMENT_KEYS,
    AUTHORIZATION_KEYS,
    COVERAGE_KEYS,
    ENVELOPE_KEYS,
    LINE_KEYS,
)
from claimguard.edu.intake import dump_envelope
from claimguard.edu.intake.fhir_source import (
    ALL_FIELD_PATHS,
    SUPPORTED_FIELDS,
    UNSUPPORTED_FIELDS,
    FhirIntakeError,
    project_bundle,
    read_bundles,
)

from tests.edu import PACK_ROOT, requires_pack

SPLITS = ("development", "validation", "stress")

CONTAINERS = ("coverage", "lines", "authorizations", "attachments")

#: The exact gaps this projection declares, from docs/11's "Deliberate limitations".
EXPECTED_UNSUPPORTED = (
    "/schema_version",
    "/notes",
    "/lines/*/line_id",
    "/attachments/*/service_code",
    "/attachments/*/document_status",
    "/authorizations/*/patient_id",
    "/authorizations/*/service_code",
    "/authorizations/*/status",
    "/authorizations/*/valid_from",
    "/authorizations/*/valid_to",
    "/authorizations/*/max_quantity",
)

_OMIT = object()


# ---------------------------------------------------------------------------
# The report itself
# ---------------------------------------------------------------------------


def test_unsupported_paths_are_the_documented_gaps() -> None:
    """The declared gaps are exactly the sidecar-only fields docs/11 names."""
    assert tuple(field.path for field in UNSUPPORTED_FIELDS) == EXPECTED_UNSUPPORTED
    assert all(field.reason.strip() for field in UNSUPPORTED_FIELDS)


def test_supported_and_unsupported_partition_the_envelope_contract() -> None:
    """No envelope field is dropped silently and none is claimed twice."""
    contract_paths = {
        *(f"/{key}" for key in ENVELOPE_KEYS if key not in CONTAINERS),
        *(f"/coverage/{key}" for key in COVERAGE_KEYS),
        *(f"/lines/*/{key}" for key in LINE_KEYS),
        *(f"/authorizations/*/{key}" for key in AUTHORIZATION_KEYS),
        *(f"/attachments/*/{key}" for key in ATTACHMENT_KEYS),
    }
    unsupported = {field.path for field in UNSUPPORTED_FIELDS}

    assert set(ALL_FIELD_PATHS) == contract_paths
    assert set(SUPPORTED_FIELDS) | unsupported == contract_paths
    assert set(SUPPORTED_FIELDS).isdisjoint(unsupported)


# ---------------------------------------------------------------------------
# Recovery, bundle by bundle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("split", SPLITS)
@requires_pack
def test_projection_recovers_exactly_the_supported_fields(split: str) -> None:
    """For every bundle, the projection equals the envelope restricted to the claimed fields.

    This single comparison proves recovery, ordering, absence of invention and
    absence of silent loss at once: dropping a supported field, adding an
    unsupported one, or reordering a child array all break it.
    """
    claims = _envelopes(PACK_ROOT / "data" / split / "claims.jsonl")
    bundles = read_bundles(PACK_ROOT / "data" / split / "fhir_bundles.jsonl")
    assert len(bundles) == len(claims)

    supported = frozenset(SUPPORTED_FIELDS)
    for envelope, bundle in zip(claims, bundles, strict=True):
        projection = project_bundle(bundle)
        assert dump_envelope(projection.envelope) == dump_envelope(
            _restrict(envelope, "", supported)
        )


@requires_pack
def test_projection_order_follows_the_bundle_arrays() -> None:
    """Claim.item, supportingInfo and preAuthRef order is the order the bundle states."""
    bundles = read_bundles(PACK_ROOT / "data" / "development" / "fhir_bundles.jsonl")
    assert len(bundles) == 400

    seen_attachments = 0
    for bundle in bundles:
        claim = _claim_of(bundle)
        projected = project_bundle(bundle).envelope

        item_codes = [
            item["productOrService"]["coding"][0]["code"]
            for item in cast("list[dict[str, Any]]", claim["item"])
        ]
        assert [
            line["service_code"] for line in cast("list[dict[str, Any]]", projected["lines"])
        ] == item_codes

        supporting = [
            entry["valueReference"]["reference"].rsplit("/", 1)[-1]
            for entry in cast("list[dict[str, Any]]", claim.get("supportingInfo", []))
            if entry["category"]["coding"][0]["code"] == "attachment"
        ]
        assert [
            record["attachment_id"]
            for record in cast("list[dict[str, Any]]", projected["attachments"])
        ] == supporting
        seen_attachments += len(supporting)

        pre_auth = [
            reference
            for insurance in cast("list[dict[str, Any]]", claim["insurance"])
            for reference in insurance.get("preAuthRef", [])
        ]
        assert [
            record["authorization_id"]
            for record in cast("list[dict[str, Any]]", projected["authorizations"])
        ] == pre_auth
    assert seen_attachments == 245


@requires_pack
def test_number_text_is_preserved_for_the_whole_split() -> None:
    """Money and quantities keep the exact literal, ints stay ints, floats stay floats."""
    claims = _envelopes(PACK_ROOT / "data" / "stress" / "claims.jsonl")
    bundles = read_bundles(PACK_ROOT / "data" / "stress" / "fhir_bundles.jsonl")

    decimals = 0
    for envelope, bundle in zip(claims, bundles, strict=True):
        rendered = dump_envelope(project_bundle(bundle).envelope)
        assert f'"total_amount": {json.dumps(envelope["total_amount"])}' in rendered
        for line in envelope["lines"]:
            if line["quantity"] is not None and "." in json.dumps(line["quantity"]):
                assert f'"quantity": {json.dumps(line["quantity"])}' in rendered
                decimals += 1
    assert decimals > 0


# ---------------------------------------------------------------------------
# Refusals: a bundle that cannot be projected says so
# ---------------------------------------------------------------------------


def _bundle() -> dict[str, Any]:
    """A minimal single-claim bundle with a resolvable patient, coverage and organization."""
    patient = "https://claimguard.example/fhir/Patient/PAT-1"
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"fullUrl": patient, "resource": {"resourceType": "Patient", "id": "PAT-1"}},
            {
                "fullUrl": "https://claimguard.example/fhir/Organization/EDU-PROV-01",
                "resource": {"resourceType": "Organization", "id": "EDU-PROV-01"},
            },
            {
                "fullUrl": "https://claimguard.example/fhir/Organization/EDU-PAYER",
                "resource": {"resourceType": "Organization", "id": "EDU-PAYER"},
            },
            {
                "fullUrl": "https://claimguard.example/fhir/Coverage/COV-1",
                "resource": {
                    "resourceType": "Coverage",
                    "id": "COV-1",
                    "status": "active",
                    "beneficiary": {"reference": patient},
                    "subscriberId": "MEM-1",
                    "period": {"start": "2026-01-01"},
                    "class": [
                        {
                            "type": {"coding": [{"code": "plan"}]},
                            "value": "EDU-BASIC",
                        }
                    ],
                },
            },
            {
                "fullUrl": "https://claimguard.example/fhir/Claim/CG-1",
                "resource": {
                    "resourceType": "Claim",
                    "id": "CG-1",
                    "status": "active",
                    "use": "claim",
                    "patient": {"reference": patient},
                    "created": "2026-01-05",
                    "provider": {
                        "reference": "https://claimguard.example/fhir/Organization/EDU-PROV-01"
                    },
                    "insurer": {
                        "reference": "https://claimguard.example/fhir/Organization/EDU-PAYER"
                    },
                    "insurance": [
                        {
                            "sequence": 1,
                            "focal": True,
                            "coverage": {
                                "reference": "https://claimguard.example/fhir/Coverage/COV-1"
                            },
                            "preAuthRef": ["AUTH-1"],
                        }
                    ],
                    "item": [
                        {
                            "sequence": 1,
                            "productOrService": {"coding": [{"code": "SVC-LAB"}]},
                            "servicedDate": "2026-01-05",
                            "quantity": {"value": 2},
                            "unitPrice": {"value": 12.5, "currency": "SAR"},
                            "net": {"value": 25, "currency": "SAR"},
                        }
                    ],
                    "total": {"value": 25, "currency": "SAR"},
                    "identifier": [
                        {"system": "https://claimguard.example/ids/invoice", "value": "INV-1"}
                    ],
                },
            },
        ],
    }


def test_minimal_bundle_projects_the_claimed_fields() -> None:
    """A bare bundle yields exactly the supported keys, with nothing filled in."""
    projection = project_bundle(_bundle())

    assert "schema_version" not in projection.envelope
    assert "notes" not in projection.envelope
    assert list(projection.envelope) == [
        key for key in ENVELOPE_KEYS if key not in ("schema_version", "notes")
    ]
    assert projection.envelope["claim_id"] == "CG-1"
    assert projection.envelope["invoice_number"] == "INV-1"
    assert projection.envelope["policy_id"] == "EDU-BASIC"
    assert projection.envelope["submission_date"] == "2026-01-05"
    assert projection.envelope["total_amount"] == 25
    assert projection.envelope["coverage"] == {
        "coverage_id": "COV-1",
        "status": "active",
        "beneficiary_patient_id": "PAT-1",
        "member_id": "MEM-1",
        "start_date": "2026-01-01",
        "end_date": None,
    }
    assert projection.envelope["lines"] == [
        {
            "service_code": "SVC-LAB",
            "service_date": "2026-01-05",
            "modifier": None,
            "quantity": 2,
            "unit_price": Decimal("12.5"),
            "net_amount": 25,
            "authorization_id": None,
        }
    ]
    assert projection.envelope["authorizations"] == [{"authorization_id": "AUTH-1"}]


def test_bundle_without_a_claim_is_refused() -> None:
    """A bundle with no Claim resource has no envelope to project."""
    bundle = _bundle()
    bundle["entry"] = [
        entry
        for entry in cast("list[Any]", bundle["entry"])
        if entry["resource"]["resourceType"] != "Claim"
    ]

    with pytest.raises(FhirIntakeError, match="no Claim resource"):
        project_bundle(bundle)


def test_non_bundle_is_refused() -> None:
    """The projection only accepts a Bundle resource."""
    with pytest.raises(FhirIntakeError, match="Bundle"):
        project_bundle({"resourceType": "Claim", "id": "CG-1"})


def test_dangling_reference_is_refused_rather_than_repaired() -> None:
    """An unresolvable reference is a finding: the projection stops, it does not null it."""
    bundle = _bundle()
    claim = _claim_of(bundle)
    claim["provider"] = {"reference": "https://claimguard.example/fhir/Organization/EDU-GONE"}

    with pytest.raises(FhirIntakeError, match=r"Claim\.provider"):
        project_bundle(bundle)


def test_undecodable_document_data_is_refused() -> None:
    """A document whose base64 body cannot be decoded is an intake error."""
    bundle = _bundle()
    patient = "https://claimguard.example/fhir/Patient/PAT-1"
    cast("list[Any]", bundle["entry"]).append(
        {
            "fullUrl": "https://claimguard.example/fhir/DocumentReference/DOC-1",
            "resource": {
                "resourceType": "DocumentReference",
                "id": "DOC-1",
                "status": "current",
                "docStatus": "final",
                "type": {"coding": [{"code": "imaging-report"}]},
                "subject": {"reference": patient},
                "content": [{"attachment": {"contentType": "text/plain", "data": "not base64!"}}],
                "context": {"period": {"start": "2026-01-05"}},
            },
        }
    )
    _claim_of(bundle)["supportingInfo"] = [
        {
            "sequence": 1,
            "category": {"coding": [{"code": "attachment"}]},
            "valueReference": {
                "reference": "https://claimguard.example/fhir/DocumentReference/DOC-1"
            },
        }
    ]

    with pytest.raises(FhirIntakeError, match="not decodable"):
        project_bundle(bundle)


def test_malformed_bundle_line_is_reported_with_its_line_number(tmp_path: Path) -> None:
    """A malformed FHIR line is named, never silently skipped."""
    path = tmp_path / "fhir_bundles.jsonl"
    path.write_text('{"resourceType": "Bundle"}\nnot json\n', encoding="utf-8")

    with pytest.raises(FhirIntakeError, match=r":2: malformed JSON"):
        read_bundles(path)


# ---------------------------------------------------------------------------
# The documented judgement calls, on real data
# ---------------------------------------------------------------------------


@requires_pack
def test_document_status_is_withheld_because_the_code_space_differs() -> None:
    """A draft envelope record is 'preliminary' in HL7; shipping that would be a translation."""
    claims = _envelopes(PACK_ROOT / "data" / "development" / "claims.jsonl")
    bundles = read_bundles(PACK_ROOT / "data" / "development" / "fhir_bundles.jsonl")

    drafts = 0
    for envelope, bundle in zip(claims, bundles, strict=True):
        projected = project_bundle(bundle).envelope
        for attachment, projected_attachment in zip(
            envelope["attachments"],
            cast("list[dict[str, Any]]", projected["attachments"]),
            strict=True,
        ):
            assert "document_status" not in projected_attachment
            assert "service_code" not in projected_attachment
            assert _document_status_of(bundle, attachment["attachment_id"]) in {
                "final",
                "preliminary",
            }
            if attachment["document_status"] == "draft":
                assert _document_status_of(bundle, attachment["attachment_id"]) == "preliminary"
                drafts += 1
    assert drafts == 8


@requires_pack
def test_document_patient_is_carried_verbatim_even_when_unresolvable() -> None:
    """A business-inconsistent document patient is preserved, not repaired to the claim's."""
    claims = _envelopes(PACK_ROOT / "data" / "development" / "claims.jsonl")
    bundles = read_bundles(PACK_ROOT / "data" / "development" / "fhir_bundles.jsonl")

    mismatched = 0
    for envelope, bundle in zip(claims, bundles, strict=True):
        projected = project_bundle(bundle).envelope
        for attachment, projected_attachment in zip(
            envelope["attachments"],
            cast("list[dict[str, Any]]", projected["attachments"]),
            strict=True,
        ):
            assert projected_attachment["patient_id"] == attachment["patient_id"]
            if attachment["patient_id"] != envelope["patient_id"]:
                mismatched += 1
    assert mismatched == 4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelopes(path: Path) -> list[dict[str, Any]]:
    """The authoritative envelopes of one split."""
    return [
        cast("dict[str, Any]", json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _claim_of(bundle: dict[str, Any]) -> dict[str, Any]:
    """The Claim resource of a bundle under construction."""
    for entry in cast("list[dict[str, Any]]", bundle["entry"]):
        if entry["resource"]["resourceType"] == "Claim":
            return cast("dict[str, Any]", entry["resource"])
    raise AssertionError("bundle has no Claim resource")


def _restrict(node: Any, prefix: str, supported: frozenset[str]) -> Any:
    """Keep only the leaves whose schema path (with ``*`` for elements) is supported."""
    if isinstance(node, dict):
        mapping = cast("dict[str, Any]", node)
        kept: dict[str, Any] = {}
        for key, child in mapping.items():
            value = _restrict(child, f"{prefix}/{key}", supported)
            if value is not _OMIT:
                kept[key] = value
        return kept
    if isinstance(node, list):
        items = cast("list[Any]", node)
        elements: list[Any] = []
        for child in items:
            value = _restrict(child, f"{prefix}/*", supported)
            if value is not _OMIT:
                elements.append(value)
        return elements
    return node if prefix in supported else _OMIT


def _document_status_of(bundle: dict[str, Any], attachment_id: str) -> str:
    """The raw HL7 docStatus of one DocumentReference in a bundle."""
    for entry in cast("list[dict[str, Any]]", bundle["entry"]):
        if entry["resource"]["id"] == attachment_id:
            return str(entry["resource"]["docStatus"])
    raise AssertionError(f"no DocumentReference {attachment_id}")
