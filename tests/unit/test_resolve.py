"""Reference resolver tests — covering all five reference spellings.

The trap (07 §8 trap #1): a resolver that handles only "Patient/123" breaks on
real bundles, and it breaks SILENTLY — a claim with a dangling encounter
reference would simply produce no ENC-001 finding, looking clean.
"""

from __future__ import annotations

from typing import Any

import pytest
from claimguard.ingest.resolve import BundleIndex


def _bundle(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


def _patient(pid: str = "123") -> dict[str, Any]:
    return {"resourceType": "Patient", "id": pid, "name": [{"family": "Mansour"}]}


# ---------------------------------------------------------------------------
# The five spellings
# ---------------------------------------------------------------------------


def test_relative_typed_reference() -> None:
    index = BundleIndex(_bundle([{"resource": _patient()}]))
    resolved = index.resolve("Patient/123")
    assert resolved is not None
    assert resolved.resource_id == "123"


def test_absolute_url_reference() -> None:
    """The spelling the original spec silently failed on."""
    index = BundleIndex(
        _bundle([{"fullUrl": "http://example.org/fhir/Patient/123", "resource": _patient()}])
    )
    resolved = index.resolve("http://example.org/fhir/Patient/123")
    assert resolved is not None
    assert resolved.resource_id == "123"


def test_urn_uuid_reference() -> None:
    index = BundleIndex(
        _bundle(
            [{"fullUrl": "urn:uuid:3a4b5c6d-0000-1111-2222-333344445555", "resource": _patient()}]
        )
    )
    resolved = index.resolve("urn:uuid:3a4b5c6d-0000-1111-2222-333344445555")
    assert resolved is not None


def test_urn_oid_reference() -> None:
    index = BundleIndex(_bundle([{"fullUrl": "urn:oid:1.2.3.4.5", "resource": _patient()}]))
    resolved = index.resolve("urn:oid:1.2.3.4.5")
    assert resolved is not None


def test_contained_reference() -> None:
    """Contained resources live INSIDE the parent, addressed as '#id'."""
    claim: dict[str, Any] = {
        "resourceType": "Claim",
        "id": "CLM-1",
        "contained": [{"resourceType": "Patient", "id": "p1"}],
    }
    index = BundleIndex(_bundle([{"resource": claim}]))
    resolved = index.resolve("#p1", parent=claim)
    assert resolved is not None
    assert resolved.resource_id == "p1"


# ---------------------------------------------------------------------------
# The ambiguity trap
# ---------------------------------------------------------------------------


def test_same_id_different_types_do_not_collide() -> None:
    """Patient/42 and Claim/42 must both be addressable."""
    index = BundleIndex(
        _bundle([{"resource": _patient("42")}, {"resource": {"resourceType": "Claim", "id": "42"}}])
    )
    assert index.resolve("Patient/42") is not None
    assert index.resolve("Claim/42") is not None
    assert index.resolve("Patient/42") is not index.resolve("Claim/42")


def test_bare_id_resolves_only_when_unambiguous() -> None:
    index = BundleIndex(_bundle([{"resource": _patient("42")}]))
    assert index.resolve("42") is not None

    ambiguous = BundleIndex(
        _bundle([{"resource": _patient("42")}, {"resource": {"resourceType": "Claim", "id": "42"}}])
    )
    assert ambiguous.resolve("42") is None, "ambiguous bare id must not guess"


# ---------------------------------------------------------------------------
# Failure behaviour
# ---------------------------------------------------------------------------


def test_unresolvable_returns_none_not_raise() -> None:
    """A dangling reference is a FINDING, never a crash (ENC-001)."""
    index = BundleIndex(_bundle([{"resource": _patient()}]))
    assert index.resolve("Encounter/NOPE") is None


@pytest.mark.parametrize("bad", [None, "", "   ", "not-a-ref", 123])
def test_malformed_references_return_none(bad: Any) -> None:
    index = BundleIndex(_bundle([{"resource": _patient()}]))
    assert index.resolve(bad) is None


def test_empty_bundle_does_not_crash() -> None:
    assert len(BundleIndex({})) == 0
    assert len(BundleIndex({"resourceType": "Bundle", "entry": []})) == 0


def test_malformed_entries_are_skipped() -> None:
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "entry": [None, "string", {}, {"noResource": True}, {"resource": _patient()}],
    }
    index = BundleIndex(bundle)
    assert len(index) == 1


def test_dangling_is_recorded_for_rules() -> None:
    index = BundleIndex(_bundle([{"resource": _patient()}]))
    index.record_dangling("Encounter/NOPE", "/item/0/encounter/0", "not_found")
    report = index.report
    assert report.has_dangling
    assert report.dangling[0].raw_reference == "Encounter/NOPE"
    assert report.dangling[0].source_pointer == "/item/0/encounter/0"


# ---------------------------------------------------------------------------
# Forward references — the reason indexing is two-pass
# ---------------------------------------------------------------------------


def test_forward_reference_resolves() -> None:
    """A claim at entry 0 referencing a patient at entry 5 must resolve."""
    entries: list[dict[str, Any]] = [
        {
            "resource": {
                "resourceType": "Claim",
                "id": "CLM-1",
                "patient": {"reference": "Patient/999"},
            }
        },
        {"resource": _patient("999")},
    ]
    index = BundleIndex(_bundle(entries))
    assert index.resolve("Patient/999") is not None
