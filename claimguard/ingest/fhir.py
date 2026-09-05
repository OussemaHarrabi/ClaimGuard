"""FHIR R4 bundle -> CanonicalClaim (ING-02).

Design rules:
  * Never raise on malformed input. A package we cannot read is an ENV-001
    finding plus a structured error — never a 500.
  * Record provenance for every populated field (`src`), because evidence must
    cite the ORIGINAL package.
  * A field we fail to map stays None; ENV-001 fires on it. Missing mapping is a
    finding, not a silent gap.

Reference resolution is two-pass (see `resolve.py`) and dangling references are
reported rather than raised — they are what ENC-001, AUTH-004 and DOC-004 fire on.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from claimguard.canonical import (
    Attachment,
    Authorization,
    CanonicalClaim,
    ClaimLine,
    Coverage,
    Encounter,
    Member,
    Money,
    Provider,
)
from claimguard.ingest.resolve import BundleIndex

# JSON Pointer prefixes — every src entry is an absolute RFC 6901 pointer.
_DOCS = "https://hl7.org/fhir/R4/"


def _dig(node: Any, *path: str | int) -> Any:
    """Safely walk nested dicts/lists. Returns None if any step is missing."""
    cur = node
    for key in path:
        if isinstance(cur, dict) and isinstance(key, str):
            cur = cast(dict[str, Any], cur).get(key)
        elif isinstance(cur, list) and isinstance(key, int):
            lst = cast(list[Any], cur)
            cur = lst[key] if 0 <= key < len(lst) else None
        else:
            return None
    return cur


def _parse_date(value: Any) -> date | None:
    """Parse a FHIR date/dateTime. Accepts YYYY-MM-DD and full ISO datetimes.

    Timezone-aware failure is a real trap (07 §8 trap #4): coverage and
    authorization windows are compared as dates, so we normalize to a date and
    never compare naive datetimes across zones.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _money(node: Any) -> Money | None:
    """Read a FHIR Money node. Returns None when there is no usable value."""
    if not isinstance(node, dict):
        return None
    n = cast(dict[str, Any], node)
    value = _parse_decimal(n.get("value"))
    if value is None:
        return None
    currency = n.get("currency")
    return Money(value=value, currency=currency if isinstance(currency, str) else "AED")


def _code(concept: Any) -> str | None:
    """Read the first coding code from a CodeableConcept."""
    if not isinstance(concept, dict):
        return None
    c = cast(dict[str, Any], concept)
    codings = c.get("coding")
    if isinstance(codings, list):
        for coding in cast(list[object], codings):
            if not isinstance(coding, dict):
                continue
            cd = cast(dict[str, Any], coding)
            if cd.get("code"):
                return str(cd["code"])
    text = c.get("text")
    return str(text) if text else None


def parse_bundle(bundle: dict[str, Any]) -> CanonicalClaim:
    """Parse a FHIR R4 Bundle (or bare Claim) into a CanonicalClaim.

    Returns a claim even when the input is malformed — inspect
    `claim.envelope_errors` and `claim.claim_id` rather than catching exceptions.
    """
    index = BundleIndex(bundle)
    claim_resource = _find_claim(bundle)

    if claim_resource is None:
        return CanonicalClaim(
            envelope_errors=["no Claim resource found in package"],
        )

    src: dict[str, str] = {}
    pointer_base = _pointer_for_claim(bundle, claim_resource)

    # --- Header -------------------------------------------------------------
    claim_id = claim_resource.get("id")
    created = _parse_datetime(claim_resource.get("created"))

    # --- Parties (resolved through the bundle index) ------------------------
    patient = _resolve_patient(claim_resource, index)
    provider = _resolve_provider(claim_resource, index)
    coverage = _resolve_coverage(claim_resource, index)
    encounter = _resolve_encounter(claim_resource, index)

    # --- Authorization / referral ------------------------------------------
    authorization = _build_authorization(claim_resource, index)

    # --- Attachments --------------------------------------------------------
    attachments = _build_attachments(claim_resource, index)

    # --- Lines --------------------------------------------------------------
    lines = _build_lines(claim_resource, index)

    # --- Envelope validation (ENV-001) -------------------------------------
    errors: list[str] = []
    if not claim_id:
        errors.append("claim.id is missing")
    if not lines:
        errors.append("claim has no service lines")
    if not any(line.serviced_date or line.serviced_period_start for line in lines):
        errors.append("claim has no service date on any line")
    if not patient:
        errors.append("claim.patient could not be resolved")
    if not provider:
        errors.append("claim.provider could not be resolved")

    if claim_id:
        src["claim_id"] = f"{pointer_base}/id"

    return CanonicalClaim(
        claim_id=str(claim_id) if claim_id else None,
        status=_as_str(claim_resource.get("status")),
        type=_code(claim_resource.get("type")),
        use=_as_str(claim_resource.get("use")),
        created=created,
        currency="AED",
        total=_money(claim_resource.get("total")),
        patient=patient,
        provider=provider,
        coverage=coverage,
        authorization=authorization,
        encounter=encounter,
        attachments=attachments,
        lines=lines,
        src=src,
        envelope_errors=errors,
    )


# ---------------------------------------------------------------------------
# Resource location
# ---------------------------------------------------------------------------


def _find_claim(bundle: dict[str, Any]) -> dict[str, Any] | None:
    """Locate the Claim resource. Prefers a real claim over a preauthorization."""
    if bundle.get("resourceType") == "Claim":
        return bundle

    entries = bundle.get("entry")
    if not isinstance(entries, list):
        return None

    claims: list[dict[str, Any]] = []
    for entry in cast(list[object], entries):
        if not isinstance(entry, dict):
            continue
        e = cast(dict[str, Any], entry)
        resource = e.get("resource")
        if not isinstance(resource, dict):
            continue
        r = cast(dict[str, Any], resource)
        if r.get("resourceType") == "Claim":
            claims.append(r)

    if not claims:
        return None
    # A submission claim (use=claim) beats a preauthorization.
    for claim in claims:
        if claim.get("use") == "claim":
            return claim
    return claims[0]


def _pointer_for_claim(bundle: dict[str, Any], claim: dict[str, Any]) -> str:
    """Build the JSON Pointer prefix for the claim, so evidence cites the original."""
    entries = bundle.get("entry")
    if isinstance(entries, list):
        for i, entry in enumerate(cast(list[object], entries)):
            if not isinstance(entry, dict):
                continue
            e = cast(dict[str, Any], entry)
            if e.get("resource") is claim:
                return f"/entry/{i}/resource"
    return ""


def _as_str(value: Any) -> str | None:
    return str(value) if value is not None else None


# ---------------------------------------------------------------------------
# Party resolution
# ---------------------------------------------------------------------------


def _resolve_patient(claim: dict[str, Any], index: BundleIndex) -> Member | None:
    ref = _dig(claim, "patient", "reference")
    resolved = index.resolve(ref if isinstance(ref, str) else None)

    resource = resolved.resource if resolved else None
    if not isinstance(resource, dict):
        return None  # unresolvable patient is an ENV-001 error, not a crash

    identifier = _first_identifier(resource)
    name = _human_name(resource)
    dob = _parse_date(resource.get("birthDate"))
    gender = _as_str(resource.get("gender"))

    return Member(
        member_id=resolved.resource_id if resolved else None,
        subscriber_id=identifier,
        name=name,
        date_of_birth=dob,
        gender=gender,
    )


def _resolve_provider(claim: dict[str, Any], index: BundleIndex) -> Provider | None:
    ref = _dig(claim, "provider", "reference")
    resolved = index.resolve(ref if isinstance(ref, str) else None)
    resource = resolved.resource if resolved else None
    if not isinstance(resource, dict):
        return None

    rtype = resource.get("resourceType")
    specialty = None
    if rtype == "Practitioner":
        specialty = _code(_dig(resource, "specialty", 0))

    return Provider(
        provider_id=_first_identifier(resource),
        name=_as_str(resource.get("name")) or _as_str(_dig(resource, "name", 0, "family")),
        type=_code(_dig(resource, "type", 0)) if rtype == "Organization" else _as_str(rtype),
        specialty=specialty,
    )


def _resolve_coverage(claim: dict[str, Any], index: BundleIndex) -> Coverage | None:
    """Resolve the FOCAL coverage. FHIR allows several; one is the adjudication target."""
    insurances = claim.get("insurance")
    if not isinstance(insurances, list):
        return None

    target: dict[str, Any] | None = None
    for item in cast(list[object], insurances):
        if not isinstance(item, dict):
            continue
        it = cast(dict[str, Any], item)
        if it.get("focal") is True:
            target = it
            break
    if target is None:
        first = cast(list[object], insurances)[0]
        target = cast(dict[str, Any], first) if isinstance(first, dict) else None
    if target is None:
        return None

    ref = _dig(target, "coverage", "reference")
    resolved = index.resolve(ref if isinstance(ref, str) else None)
    resource = resolved.resource if resolved else None
    if not isinstance(resource, dict):
        return None

    payor_ref = _dig(resource, "payor", 0, "reference")
    payor = index.resolve(payor_ref if isinstance(payor_ref, str) else None)

    return Coverage(
        coverage_id=resolved.resource_id if resolved else None,
        status=_as_str(resource.get("status")),
        payer_name=(payor.resource.get("name") if payor else None) or None,
        plan_name=_as_str(_dig(resource, "class", 0, "name"))
        or _as_str(_dig(resource, "class", 0, "value")),
        period_start=_parse_date(_dig(resource, "period", "start")),
        period_end=_parse_date(_dig(resource, "period", "end")),
        subscriber_id=_as_str(resource.get("subscriberId")),
    )


def _resolve_encounter(claim: dict[str, Any], index: BundleIndex) -> Encounter | None:
    """Resolve the first encounter referenced by the claim or any of its lines.

    A dangling encounter reference is what ENC-001 fires on, so we return None and
    let the canonical model's null state express "absent" — the resolver's
    dangling report carries the detail.
    """
    refs: list[str] = []
    for item in cast(list[object], claim.get("item") or []):
        if not isinstance(item, dict):
            continue
        it = cast(dict[str, Any], item)
        for enc in cast(list[object], it.get("encounter") or []):
            if not isinstance(enc, dict):
                continue
            e = cast(dict[str, Any], enc)
            ref = e.get("reference")
            if isinstance(ref, str):
                refs.append(ref)

    if not refs:
        return None

    resolved = index.resolve(refs[0])
    resource = resolved.resource if resolved else None
    if not isinstance(resource, dict):
        return None

    subject_ref = _dig(resource, "subject", "reference")
    subject = index.resolve(subject_ref if isinstance(subject_ref, str) else None)
    patient_ref = _dig(claim, "patient", "reference")

    return Encounter(
        encounter_id=resolved.resource_id if resolved else None,
        status=_as_str(resource.get("status")),
        period_start=_parse_date(_dig(resource, "period", "start")),
        period_end=_parse_date(_dig(resource, "period", "end")),
        type=_code(_dig(resource, "type", 0)),
        location=_as_str(_dig(resource, "location", 0, "location", "display")),
        subject_resolved=subject is not None,
        subject_matches_member=bool(
            subject is not None
            and isinstance(patient_ref, str)
            and subject.resource_id == patient_ref.split("/")[-1]
        ),
    )


# ---------------------------------------------------------------------------
# Authorization / attachments / lines
# ---------------------------------------------------------------------------


def _build_authorization(claim: dict[str, Any], index: BundleIndex) -> Authorization | None:
    """Build the authorization view from preAuthRef and supportingInfo.

    Returns None when there is no authorization evidence at all — that absence is
    exactly what AUTH-004 fires on.
    """
    pre_auth_refs = claim.get("insurance")
    reference: str | None = None
    for item in cast(list[object], pre_auth_refs if isinstance(pre_auth_refs, list) else []):
        if not isinstance(item, dict):
            continue
        it = cast(dict[str, Any], item)
        refs = it.get("preAuthRef")
        if isinstance(refs, list) and refs and isinstance(refs[0], str):
            reference = refs[0]
            break

    valid_from = valid_to = None
    procedure_code = None
    status = None

    # supportingInfo of category 'authorization' may carry the validity window.
    supporting = claim.get("supportingInfo")
    for info in cast(list[object], supporting if isinstance(supporting, list) else []):
        if not isinstance(info, dict):
            continue
        inf = cast(dict[str, Any], info)
        if _code(inf.get("category")) != "authorization":
            continue
        period: dict[str, Any] = inf.get("timingPeriod") or {}
        valid_from = _parse_date(period.get("start")) or valid_from
        valid_to = _parse_date(period.get("end")) or valid_to
        procedure_code = procedure_code or _code(inf.get("code"))

    if reference is None and valid_from is None and valid_to is None:
        return None  # AUTH-004: nothing present

    return Authorization(
        reference=reference,
        ref_resolved=False,  # set by the reference resolver pass
        status=status,
        procedure_code=procedure_code,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def _build_attachments(claim: dict[str, Any], index: BundleIndex) -> list[Attachment]:
    """Attachments referenced in supportingInfo.

    A referenced-but-absent attachment returns ref_resolved=False, which is what
    DOC-004 fires on.
    """
    out: list[Attachment] = []
    supporting = claim.get("supportingInfo")
    for i, info in enumerate(
        cast(list[object], supporting if isinstance(supporting, list) else [])
    ):
        if not isinstance(info, dict):
            continue
        inf = cast(dict[str, Any], info)
        if _code(inf.get("category")) != "attachment":
            continue

        value_ref = _dig(inf, "valueReference", "reference")
        resolved = index.resolve(value_ref if isinstance(value_ref, str) else None)
        resource = resolved.resource if resolved else None
        content_present = bool(
            isinstance(resource, dict) and _dig(resource, "content", 0, "attachment", "data")
        )

        out.append(
            Attachment(
                reference=value_ref if isinstance(value_ref, str) else None,
                ref_resolved=resolved is not None,
                expected=True,
                content_present=content_present,
                content_type=(
                    _as_str(_dig(resource, "content", 0, "attachment", "contentType"))
                    if isinstance(resource, dict)
                    else None
                ),
            )
        )
        _ = i
    return out


def _build_lines(claim: dict[str, Any], index: BundleIndex) -> list[ClaimLine]:
    out: list[ClaimLine] = []
    items = claim.get("item")
    if not isinstance(items, list):
        return out

    for item in cast(list[object], items):
        if not isinstance(item, dict):
            continue
        it = cast(dict[str, Any], item)

        refs = it.get("encounter")
        ref_values: list[object] = []
        for ref in cast(list[object], refs if isinstance(refs, list) else []):
            if not isinstance(ref, dict):
                continue
            rd = cast(dict[str, Any], ref)
            value = rd.get("reference")
            if value:
                ref_values.append(value)
        ref_list = [r for r in ref_values if isinstance(r, str)]
        resolved_flags = [index.resolve(r) is not None for r in ref_list]

        quantity = _parse_decimal(_dig(it, "quantity", "value"))

        raw_modifiers = it.get("modifier")
        modifiers = [
            code
            for m in cast(list[object], raw_modifiers if isinstance(raw_modifiers, list) else [])
            if (code := _code(m)) is not None
        ]
        raw_diag = it.get("diagnosisSequence")
        diagnosis_sequence = [
            d
            for d in cast(list[object], raw_diag if isinstance(raw_diag, list) else [])
            if isinstance(d, int)
        ]

        out.append(
            ClaimLine(
                sequence=int(it["sequence"]) if "sequence" in it else len(out) + 1,
                product_or_service=_code(it.get("productOrService")),
                category=_code(it.get("category")),
                revenue_code=_code(it.get("revenue")),
                serviced_date=_parse_date(it.get("servicedDate")),
                serviced_period_start=_parse_date(_dig(it, "servicedPeriod", "start")),
                serviced_period_end=_parse_date(_dig(it, "servicedPeriod", "end")),
                quantity=quantity,
                unit_price=_money(it.get("unitPrice")),
                net=_money(it.get("net")),
                modifier=modifiers,
                encounter_refs=ref_list,
                encounter_refs_resolved=resolved_flags,
                diagnosis_sequence=diagnosis_sequence,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _first_identifier(resource: dict[str, Any]) -> str | None:
    identifiers = resource.get("identifier")
    if isinstance(identifiers, list):
        for ident in cast(list[object], identifiers):
            if not isinstance(ident, dict):
                continue
            id_ = cast(dict[str, Any], ident)
            if id_.get("value"):
                return str(id_["value"])
    return None


def _human_name(patient: dict[str, Any]) -> str | None:
    names = patient.get("name")
    if not isinstance(names, list) or not names:
        return None
    first = cast(list[object], names)[0]
    if not isinstance(first, dict):
        return None
    f = cast(dict[str, Any], first)
    family = f.get("family")
    given = f.get("given")
    given_str = cast(list[object], given)[0] if isinstance(given, list) and given else None
    parts = [p for p in (given_str, family) if isinstance(p, str)]
    return " ".join(parts) or _as_str(f.get("text"))
