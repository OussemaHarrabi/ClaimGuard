"""One FHIR R4 collection Bundle -> a normalized envelope projection (INT-02).

The authoritative evaluation input is the normalized envelope; the FHIR files are
a separate integration exercise and are *deliberately* insufficient
(docs/11_FHIR_Orientation.md, "Deliberate limitations")::

    Full authorization details, policy limits, notes and some source metadata
    remain in the normalized sidecar; FHIR files alone are insufficient to
    reproduce all 15 checks. No reverse adapter is included.

So this module projects exactly the envelope fields the bundle actually carries
and *reports the rest* (:data:`UNSUPPORTED_FIELDS`, one entry per path with the
citation for why) instead of inventing a value. Nothing here repairs, infers or
coerces: a reference is read as written, a status is carried in the code space it
was written in, and free text is never parsed into a field.

Mapping (docs/11, "Mapping coverage"), each line verified against all 600 public
bundles — see ``tests/edu_intake/test_fhir_source.py``:

==================================  ==============================================
envelope                            FHIR source
==================================  ==============================================
claim_id                            Claim.id
invoice_number                      Claim.identifier (system suffix
                                    ``/ids/invoice``)
patient_id                          Claim.patient (resolved)
member_id                           Patient.identifier (system suffix
                                    ``/ids/member``)
provider_id / payer_id              Claim.provider / Claim.insurer (resolved)
policy_id                           Coverage.class where ``type.coding`` is ``plan``
diagnosis_code                      Claim.diagnosis[0].diagnosisCodeableConcept
submission_date                     Claim.created
currency / total_amount             Claim.total.currency / Claim.total.value
coverage.*                          Coverage: id, status, beneficiary, subscriberId,
                                    period
lines[].*                           Claim.item, in array order; authorization_id
                                    from the ``line-authorization-id`` extension
authorizations[].authorization_id   Claim.insurance[].preAuthRef, in array order
attachments[].*                     DocumentReference (id, type, subject, period,
                                    base64 ``content[].attachment.data``) reached
                                    through Claim.supportingInfo
==================================  ==============================================

Numbers are :class:`~decimal.Decimal` taken from the JSON literal through
:func:`claimguard.edu.intake.dump_envelope`; serialize a projection with that
function, never with :func:`json.dumps`.

The result is *partial*: it is an integration artifact, not engine input — it
omits the unsupported keys, so the pack transport validator (which requires all
17 keys plus every child key) will reject it, and :meth:`FhirProjection` says so
in :data:`CAVEATS`.

SAFETY: attachment text and any other free text is untrusted data. It is decoded
and carried verbatim; it is never interpreted as an instruction
(docs/10_Privacy_Security_and_Audit.md).
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, cast

from claimguard.edu.envelope import ENVELOPE_KEYS, to_decimal
from claimguard.edu.intake import (
    ARRAY_CONTAINER_KEYS,
    CHILD_KEYS,
    SINGLE_CONTAINER_KEYS,
    Envelope,
)
from claimguard.ingest.resolve import BundleIndex, IndexedResource

#: Suffix of the Claim.identifier system that carries the submitted invoice number.
_INVOICE_SYSTEM_SUFFIX: Final = "/ids/invoice"

#: Suffix of the Patient.identifier system that carries membership.
_MEMBER_SYSTEM_SUFFIX: Final = "/ids/member"

#: The teaching extension that carries the per-line authorization reference
#: (docs/11: "Claim.insurance.preAuthRef plus a teaching line extension").
_LINE_AUTHORIZATION_URL: Final = "line-authorization-id"

#: docs/11_FHIR_Orientation.md, "Deliberate limitations" — the sentence that makes
#: the sidecar-only fields explicit.
_SIDECAR_CITATION: Final = (
    "docs/11_FHIR_Orientation.md, 'Deliberate limitations': full authorization details, "
    "policy limits, notes and some source metadata remain in the normalized sidecar; FHIR "
    "files alone are insufficient to reproduce all 15 checks."
)


class FhirIntakeError(ValueError):
    """The bundle cannot be projected: it is not a Bundle, or it is malformed."""


@dataclass(frozen=True)
class UnsupportedField:
    """One envelope path this projection cannot supply, and why not."""

    path: str
    reason: str


#: Every leaf path of the 17-key envelope; ``*`` stands for one element of an array
#: container (``coverage`` is a single object, so it has no ``*``).
ALL_FIELD_PATHS: Final = (
    *(f"/{key}" for key in ENVELOPE_KEYS if key not in CHILD_KEYS),
    *(f"/{child}/{leaf}" for child in SINGLE_CONTAINER_KEYS for leaf in CHILD_KEYS[child]),
    *(f"/{child}/*/{leaf}" for child in ARRAY_CONTAINER_KEYS for leaf in CHILD_KEYS[child]),
)

#: The envelope paths a pack FHIR collection Bundle cannot supply.
UNSUPPORTED_FIELDS: Final[tuple[UnsupportedField, ...]] = (
    UnsupportedField(
        "/schema_version",
        "The bundle carries no teaching-contract version marker (no Bundle.meta.versionId, no "
        "Claim.meta); the contract version exists only in the normalized sidecar.",
    ),
    UnsupportedField(
        "/notes",
        "Claim.note is absent from every public bundle; notes are free text and stay in the "
        "normalized sidecar. " + _SIDECAR_CITATION,
    ),
    UnsupportedField(
        "/lines/*/line_id",
        "Claim.item carries only the ordinal Claim.item.sequence; the stable L1/L2 identifier is "
        "not projected anywhere. Deriving 'L<sequence>' would invent a value the bundle does not "
        "carry (docs/03_Data_Dictionary.md: affected_line_ids use the stable identifiers, not "
        "array offsets).",
    ),
    UnsupportedField(
        "/attachments/*/service_code",
        "No coded field exists: the service code appears only inside the free text of "
        "DocumentReference.description ('Synthetic <code>') and of the document itself. "
        "Attachment text is untrusted data and is never parsed into field values.",
    ),
    UnsupportedField(
        "/attachments/*/document_status",
        "DocumentReference.docStatus is written in the HL7 code space "
        "(preliminary|final|amended|entered-in-error) while the envelope uses its own vocabulary; "
        "the pack documents no inverse mapping, so carrying docStatus verbatim would silently "
        "change the value (observed in the public splits: draft<->preliminary 15x, final<->final "
        "357x). Shipping 'preliminary' as document_status would be a translation this module is "
        "not authorised to make.",
    ),
    *(
        UnsupportedField(
            f"/authorizations/*/{key}",
            "Only the authorization *reference* is projected (Claim.insurance.preAuthRef and the "
            "teaching line extension); the record itself is sidecar-only. " + _SIDECAR_CITATION,
        )
        for key in CHILD_KEYS["authorizations"]
        if key != "authorization_id"
    ),
)

#: The envelope paths this projection does supply, derived so that supported and
#: unsupported always partition :data:`ALL_FIELD_PATHS`.
SUPPORTED_FIELDS: Final[tuple[str, ...]] = tuple(
    path for path in ALL_FIELD_PATHS if path not in {field.path for field in UNSUPPORTED_FIELDS}
)

#: Judgement calls of this projection, stated where a consumer will read them.
CAVEATS: Final[tuple[str, ...]] = (
    "/policy_id is projected from Coverage.class where type.coding is 'plan': the plan-class "
    "slot is the HL7-standard place for a plan identifier, although docs/11's mapping table does "
    "not name policy_id. The value matched the envelope verbatim in all 600 public bundles.",
    "/submission_date is projected from Claim.created, the FHIR claim creation date; docs/11's "
    "mapping table does not name it. The value matched the envelope verbatim in all 600 public "
    "bundles.",
    "/member_id (Patient.identifier) and /coverage/member_id (Coverage.subscriberId) are read "
    "from different resources and legitimately disagree in 43 of 600 public bundles — a "
    "deliberate business inconsistency. Both are carried as written rather than collapsed.",
    "/attachments/*/patient_id is the identifier written in DocumentReference.subject, not a "
    "resolved Patient: 8 of 372 supporting records reference a patient outside the bundle "
    "(docs/11: 'Some business-inconsistent records intentionally reference a different document "
    "patient'). The reference is carried verbatim and never repaired.",
    "Numbers are decimal.Decimal derived from the JSON literal; serialize with "
    "claimguard.edu.intake.dump_envelope, which keeps the exact literal.",
    "The projection is partial by design: it omits the unsupported keys, so the pack transport "
    "validator will reject it. It is an integration artifact, not engine input.",
)


@dataclass(frozen=True)
class FhirProjection:
    """One bundle projected onto the envelope fields FHIR actually carries."""

    envelope: Envelope
    supported_fields: tuple[str, ...] = SUPPORTED_FIELDS
    unsupported_fields: tuple[UnsupportedField, ...] = UNSUPPORTED_FIELDS
    caveats: tuple[str, ...] = CAVEATS


# ---------------------------------------------------------------------------
# Safe FHIR node access
# ---------------------------------------------------------------------------


def _child(node: Any, *path: str) -> Any:
    """Walk nested mappings; return None as soon as a step is absent or not a mapping."""
    current: Any = node
    for step in path:
        if not isinstance(current, Mapping):
            return None
        current = cast("Mapping[str, Any]", current).get(step)
    return current


def _text(node: Any, *path: str) -> str | None:
    """A non-empty string node, or None."""
    value = _child(node, *path)
    return value if isinstance(value, str) and value else None


def _number(node: Any, *path: str) -> Decimal | None:
    """A JSON number node as an exact Decimal, or None (bools are not numbers)."""
    value = _child(node, *path)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return to_decimal(value)


def _entries(node: Any, *path: str) -> list[Any]:
    """An array node as a list, or an empty list."""
    value = _child(node, *path)
    return cast("list[Any]", value) if isinstance(value, list) else []


def _coding_code(concept: Any) -> str | None:
    """The first coding code of a CodeableConcept (the public bundles set exactly one)."""
    for coding in _entries(concept, "coding"):
        code = _text(coding, "code")
        if code is not None:
            return code
    return None


def _reference_id(reference: str) -> str:
    """The identifier written in a FHIR reference ('Patient/P-1' or an absolute URL)."""
    return reference.rstrip("/").rsplit("/", 1)[-1]


def _required(value: str | None, label: str) -> str:
    """Return ``value`` or fail: the envelope requires a non-null value at ``label``."""
    if value is None:
        raise FhirIntakeError(f"{label} is absent but the envelope requires a non-null value")
    return value


# ---------------------------------------------------------------------------
# Bundle entry points
# ---------------------------------------------------------------------------


def _single_claim(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """The bundle's one Claim resource."""
    claims = [
        cast("dict[str, Any]", entry["resource"])
        for entry in _entries(bundle, "entry")
        if isinstance(entry, Mapping) and _text(entry, "resource", "resourceType") == "Claim"
    ]
    if not claims:
        raise FhirIntakeError("the bundle contains no Claim resource")
    if len(claims) > 1:
        raise FhirIntakeError(
            f"the bundle contains {len(claims)} Claim resources; this projection handles one claim "
            "per bundle"
        )
    return claims[0]


def _resolved(index: BundleIndex, reference: str, label: str) -> IndexedResource:
    """Resolve ``reference`` inside the bundle, or fail naming the dangling reference.

    A dangling reference is never repaired and never silently treated as absent:
    ``claimguard.ingest.resolve`` is the authority on resolution and reports the
    miss, so the projection stops instead of emitting a partial truth.
    """
    found = index.resolve(reference)
    if found is None:
        raise FhirIntakeError(f"{label}: reference {reference!r} does not resolve in this bundle")
    return found


def _focal_coverage_reference(claim: Mapping[str, Any]) -> str:
    """The Coverage reference the claim adjudicates against (focal, else the first)."""
    insurance = _entries(claim, "insurance")
    ordered = sorted(insurance, key=lambda entry: not bool(_child(entry, "focal")))
    for entry in ordered:
        reference = _text(entry, "coverage", "reference")
        if reference is not None:
            return reference
    raise FhirIntakeError("Claim.insurance has no coverage reference to project coverage from")


def _identifier_value(container: Any, system_suffix: str) -> str | None:
    """The value of the first identifier whose system ends with ``system_suffix``."""
    for identifier in _entries(container, "identifier"):
        system = _text(identifier, "system")
        if system is not None and system.endswith(system_suffix):
            return _text(identifier, "value")
    return None


# ---------------------------------------------------------------------------
# Nested records
# ---------------------------------------------------------------------------


def _coverage_record(index: BundleIndex, coverage: Mapping[str, Any]) -> dict[str, Any]:
    """The envelope coverage record from a FHIR Coverage resource."""
    beneficiary = _text(coverage, "beneficiary", "reference")
    return {
        "coverage_id": _required(_text(coverage, "id"), "Coverage.id"),
        "status": _text(coverage, "status"),
        "beneficiary_patient_id": (
            _resolved(index, beneficiary, "Coverage.beneficiary").resource_id
            if beneficiary is not None
            else None
        ),
        "member_id": _text(coverage, "subscriberId"),
        "start_date": _text(coverage, "period", "start"),
        "end_date": _text(coverage, "period", "end"),
    }


def _line_record(item: Mapping[str, Any]) -> dict[str, Any]:
    """The envelope line record from one Claim.item, minus the unsupported line_id."""
    modifiers = _entries(item, "modifier")
    extension = next(
        (
            _text(entry, "valueString")
            for entry in _entries(item, "extension")
            if (_text(entry, "url") or "").endswith(_LINE_AUTHORIZATION_URL)
        ),
        None,
    )
    return {
        "service_code": _coding_code(_child(item, "productOrService")),
        "service_date": _text(item, "servicedDate"),
        "modifier": _coding_code(modifiers[0]) if modifiers else None,
        "quantity": _number(item, "quantity", "value"),
        "unit_price": _number(item, "unitPrice", "value"),
        "net_amount": _number(item, "net", "value"),
        "authorization_id": extension,
    }


def _document_text(document: Mapping[str, Any]) -> str:
    """The decoded ``text/plain`` body of a DocumentReference (untrusted data)."""
    for content in _entries(document, "content"):
        data = _text(content, "attachment", "data")
        if data is None:
            continue
        try:
            return base64.b64decode(data, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise FhirIntakeError(
                f"DocumentReference {_text(document, 'id')!r}: attachment data is not decodable "
                f"base64 UTF-8 ({exc})"
            ) from exc
    raise FhirIntakeError(
        f"DocumentReference {_text(document, 'id')!r}: no content[].attachment.data to decode"
    )


def _attachment_record(index: BundleIndex, reference: str) -> dict[str, Any]:
    """The envelope attachment record from a referenced DocumentReference.

    The service date is ``context.period.start`` (falling back to ``end``): the pack
    writes a single-day period, so the start is the date the document belongs to.
    """
    document = _resolved(index, reference, "Claim.supportingInfo").resource
    subject = _text(document, "subject", "reference")
    service_date = _text(document, "context", "period", "start") or _text(
        document, "context", "period", "end"
    )
    return {
        "attachment_id": _required(_text(document, "id"), "DocumentReference.id"),
        "type": _required(_coding_code(_child(document, "type")), "DocumentReference.type"),
        "patient_id": _required(
            _reference_id(subject) if subject is not None else None,
            "DocumentReference.subject.reference",
        ),
        "service_date": _required(service_date, "DocumentReference.context.period"),
        "text": _document_text(document),
    }


def _attachment_references(claim: Mapping[str, Any]) -> list[str]:
    """DocumentReference references of Claim.supportingInfo, in array order."""
    references: list[str] = []
    for entry in _entries(claim, "supportingInfo"):
        if _coding_code(_child(entry, "category")) != "attachment":
            continue
        reference = _text(entry, "valueReference", "reference")
        if reference is not None:
            references.append(reference)
    return references


def _authorization_ids(claim: Mapping[str, Any]) -> list[str]:
    """Authorization ids of Claim.insurance[].preAuthRef, verbatim and in order."""
    return [
        reference
        for insurance in _entries(claim, "insurance")
        for reference in _entries(insurance, "preAuthRef")
        if isinstance(reference, str)
    ]


def _policy_id(coverage: Mapping[str, Any]) -> str:
    """The plan identifier carried by Coverage.class (type.coding == plan)."""
    for entry in _entries(coverage, "class"):
        if _coding_code(_child(entry, "type")) == "plan":
            value = _text(entry, "value")
            if value is not None:
                return value
    raise FhirIntakeError(
        "Coverage.class has no value for the plan class; policy_id cannot be projected"
    )


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def project_bundle(bundle: dict[str, Any]) -> FhirProjection:
    """Project one FHIR R4 collection Bundle onto the supportable envelope fields.

    Returns a :class:`FhirProjection` whose ``envelope`` holds only the supported
    paths — in the contract's key order — together with the supported/unsupported
    field report and the projection's caveats. The caller decides what to do about
    the gaps; this function never fills one.

    Raises :class:`FhirIntakeError` when the bundle is not a Bundle, when it does
    not carry exactly one Claim, when a reference the projection needs does not
    resolve, or when a *non-nullable* envelope value is absent from the bundle.
    """
    if bundle.get("resourceType") != "Bundle":
        raise FhirIntakeError("expected a FHIR Bundle resource")

    index = BundleIndex(bundle)
    claim = _single_claim(bundle)
    patient = _resolved(index, _required_reference(claim, "patient"), "Claim.patient")
    coverage = _resolved(index, _focal_coverage_reference(claim), "Claim.insurance.coverage")
    diagnoses = _entries(claim, "diagnosis")

    projected: dict[str, Any] = {
        "claim_id": _required(_text(claim, "id"), "Claim.id"),
        "invoice_number": _identifier_value(claim, _INVOICE_SYSTEM_SUFFIX),
        "patient_id": patient.resource_id,
        "member_id": _identifier_value(patient.resource, _MEMBER_SYSTEM_SUFFIX),
        "provider_id": _resolved(
            index, _required_reference(claim, "provider"), "Claim.provider"
        ).resource_id,
        "payer_id": _resolved(
            index, _required_reference(claim, "insurer"), "Claim.insurer"
        ).resource_id,
        "policy_id": _policy_id(coverage.resource),
        "diagnosis_code": (
            _coding_code(_child(diagnoses[0], "diagnosisCodeableConcept")) if diagnoses else None
        ),
        "submission_date": _required(_text(claim, "created"), "Claim.created"),
        "currency": _required(_text(claim, "total", "currency"), "Claim.total.currency"),
        "total_amount": _number(claim, "total", "value"),
        "coverage": _coverage_record(index, coverage.resource),
        "lines": [_line_record(item) for item in _entries(claim, "item")],
        "authorizations": [
            {"authorization_id": reference} for reference in _authorization_ids(claim)
        ],
        "attachments": [
            _attachment_record(index, reference) for reference in _attachment_references(claim)
        ],
    }
    envelope: Envelope = {key: projected[key] for key in ENVELOPE_KEYS if key in projected}
    return FhirProjection(envelope=envelope)


def _required_reference(claim: Mapping[str, Any], field: str) -> str:
    """A required reference of the Claim resource."""
    return _required(_text(claim, field, "reference"), f"Claim.{field}.reference")


def read_bundles(path: str | Path) -> list[dict[str, Any]]:
    """Load a pack ``fhir_bundles.jsonl`` file into parsed Bundle objects.

    A malformed line is an intake error naming the line, never a silent skip.
    """
    bundles: list[dict[str, Any]] = []
    source = Path(path)
    for line_number, text in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        if not text.strip():
            continue
        try:
            parsed: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FhirIntakeError(
                f"{source.name}:{line_number}: malformed JSON: {exc.msg}"
            ) from exc
        if not isinstance(parsed, dict):
            raise FhirIntakeError(f"{source.name}:{line_number}: expected a JSON object")
        bundles.append(cast("dict[str, Any]", parsed))
    return bundles
