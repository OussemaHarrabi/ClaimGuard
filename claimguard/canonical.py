"""Canonical claim model — the single internal representation of a claim package.

WHY NORMALIZE
-------------
FHIR R4 is verbose and has many optional paths; CSV is flat. Rules must not care
which format arrived. We map both into one stable shape, then evaluate rules
against a dense projection of that shape (see `to_rule_payload`).

PROVENANCE
----------
Every canonical field records the JSON Pointer it came from (`src`), so evidence
can always cite the ORIGINAL package rather than our copy. A field the
canonicalizer failed to map becomes None and ENV-001 fires on it — a missing
mapping is a finding, never a silent gap (05 §1.2).

THE camelCase CONTRACT (P0-1)
-----------------------------
`to_rule_payload()` emits **camelCase** keys via Pydantic aliases, because every
CEL condition in the rule catalogue is authored in camelCase
(`payload.coverage.periodEnd`, `i.productOrService`, ...).

An earlier version called `model_dump(by_alias=False)`, producing snake_case keys.
Every rule then silently failed to fire — the engine found nothing and reported
success. A validation gate whose rules never fire is worse than one that crashes,
because it ships. `tests/unit/test_payload_contract.py` guards this permanently.

THE DENSITY CONTRACT
--------------------
Optional nested models are emitted as null-filled objects, not `null`. Without
this, a CEL expression like `payload.authorization.validFrom <= payload.anchorDate`
cannot be navigated when no authorization exists: it yields null, the rule does
not fire, and a genuinely missing authorization goes undetected. Same failure
class as P0-1, so it is fixed at the same layer.

Do NOT add a field without an alias. Do NOT change `to_rule_payload` to dump by
field name. Do NOT hand-build partial dicts that collide with the model dump.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class CanonicalBase(BaseModel):
    """Base for all canonical models.

    `populate_by_name=True` lets the canonicalizer construct models using Python
    field names (snake_case) while serialization uses the camelCase aliases the
    CEL conditions expect.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        frozen=False,
        validate_assignment=True,
        extra="forbid",  # a typo in a field name must fail loudly, not pass silently
    )

    def to_rule_payload(self) -> dict[str, Any]:
        """Dense camelCase projection for the CEL engine.

        Dense = every key a rule might read is present, null when absent, so CEL
        navigates to null instead of erroring.

        P0-1: dump BY ALIAS (camelCase) — the catalogue is authored in camelCase.
        P0-2: pure alias dump + derived `anchorDate`; never merge partial dicts.
        Density: absent nested models become null-filled objects.
        """
        payload = self.model_dump(
            by_alias=True,
            mode="json",
            exclude={"src"},  # provenance is metadata, not rule input
        )
        payload = _densify_nested(payload, type(self))

        if isinstance(self, CanonicalClaim):
            payload["anchorDate"] = self.anchor_date.isoformat() if self.anchor_date else None
        return payload


class Money(CanonicalBase):
    """Monetary amount. Decimal throughout — never float."""

    value: Annotated[Decimal | None, Field(alias="value")] = None
    currency: Annotated[str, Field(alias="currency")] = "AED"


# ---------------------------------------------------------------------------
# Party / coverage models
# ---------------------------------------------------------------------------


class Member(CanonicalBase):
    """The patient / insured person."""

    member_id: Annotated[str | None, Field(alias="memberId")] = None
    subscriber_id: Annotated[str | None, Field(alias="subscriberId")] = None
    name: Annotated[str | None, Field(alias="name")] = None
    date_of_birth: Annotated[date | None, Field(alias="dateOfBirth")] = None
    gender: Annotated[str | None, Field(alias="gender")] = None


class Provider(CanonicalBase):
    """The submitting organization or practitioner (ID-005 target)."""

    provider_id: Annotated[str | None, Field(alias="providerId")] = None
    name: Annotated[str | None, Field(alias="name")] = None
    type: Annotated[str | None, Field(alias="type")] = None
    specialty: Annotated[str | None, Field(alias="specialty")] = None


class Coverage(CanonicalBase):
    """Insurance coverage. `period_end` is the COV-001 target."""

    coverage_id: Annotated[str | None, Field(alias="coverageId")] = None
    status: Annotated[str | None, Field(alias="status")] = None
    payer_name: Annotated[str | None, Field(alias="payerName")] = None
    plan_name: Annotated[str | None, Field(alias="planName")] = None
    period_start: Annotated[date | None, Field(alias="periodStart")] = None
    period_end: Annotated[date | None, Field(alias="periodEnd")] = None
    subscriber_id: Annotated[str | None, Field(alias="subscriberId")] = None


class BenefitBalance(CanonicalBase):
    """Remaining benefit for a service category. The COV-008 target.

    `remaining` is derived (limit - used); its provenance points at both inputs.
    """

    category: Annotated[str | None, Field(alias="category")] = None
    limit_amount: Annotated[Decimal | None, Field(alias="limitAmount")] = None
    used_amount: Annotated[Decimal | None, Field(alias="usedAmount")] = None
    remaining: Annotated[Decimal | None, Field(alias="remaining")] = None


class Authorization(CanonicalBase):
    """Prior authorization / referral. AUTH-004/006/009 target."""

    reference: Annotated[str | None, Field(alias="reference")] = None
    ref_resolved: Annotated[bool, Field(alias="refResolved")] = False
    status: Annotated[str | None, Field(alias="status")] = None
    procedure_code: Annotated[str | None, Field(alias="procedureCode")] = None
    valid_from: Annotated[date | None, Field(alias="validFrom")] = None
    valid_to: Annotated[date | None, Field(alias="validTo")] = None
    authorized_provider: Annotated[str | None, Field(alias="authorizedProvider")] = None


class Attachment(CanonicalBase):
    """A referenced supporting document. DOC-004 target."""

    reference: Annotated[str | None, Field(alias="reference")] = None
    ref_resolved: Annotated[bool, Field(alias="refResolved")] = False
    expected: Annotated[bool, Field(alias="expected")] = False
    content_present: Annotated[bool, Field(alias="contentPresent")] = False
    content_type: Annotated[str | None, Field(alias="contentType")] = None
    content_hash: Annotated[str | None, Field(alias="contentHash")] = None


class Encounter(CanonicalBase):
    """The visit. ENC-001 / ID-002 target."""

    encounter_id: Annotated[str | None, Field(alias="encounterId")] = None
    status: Annotated[str | None, Field(alias="status")] = None
    period_start: Annotated[date | None, Field(alias="periodStart")] = None
    period_end: Annotated[date | None, Field(alias="periodEnd")] = None
    type: Annotated[str | None, Field(alias="type")] = None
    location: Annotated[str | None, Field(alias="location")] = None
    subject_resolved: Annotated[bool, Field(alias="subjectResolved")] = False
    subject_matches_member: Annotated[bool, Field(alias="subjectMatchesMember")] = False


class ClaimLine(CanonicalBase):
    """One charged service line. DUP-002 / INT-003 / AUTH-009 target."""

    sequence: Annotated[int, Field(alias="sequence")]
    product_or_service: Annotated[str | None, Field(alias="productOrService")] = None
    category: Annotated[str | None, Field(alias="category")] = None
    revenue_code: Annotated[str | None, Field(alias="revenueCode")] = None
    serviced_date: Annotated[date | None, Field(alias="servicedDate")] = None
    serviced_period_start: Annotated[date | None, Field(alias="servicedPeriodStart")] = None
    serviced_period_end: Annotated[date | None, Field(alias="servicedPeriodEnd")] = None
    quantity: Annotated[Decimal | None, Field(alias="quantity")] = None
    unit_price: Annotated[Money | None, Field(alias="unitPrice")] = None
    net: Annotated[Money | None, Field(alias="net")] = None
    modifier: Annotated[list[str], Field(alias="modifier")] = Field(default_factory=list[str])
    encounter_refs: Annotated[list[str], Field(alias="encounterRefs")] = Field(
        default_factory=list[str]
    )
    encounter_refs_resolved: Annotated[list[bool], Field(alias="encounterRefsResolved")] = Field(
        default_factory=list[bool]
    )
    diagnosis_sequence: Annotated[list[int], Field(alias="diagnosisSequence")] = Field(
        default_factory=list[int]
    )


# ---------------------------------------------------------------------------
# The claim package
# ---------------------------------------------------------------------------


class CanonicalClaim(CanonicalBase):
    """The normalized claim package — the audited artifact.

    `src` maps every populated field to the JSON Pointer it came from in the
    original package. This is the backbone of explainability: evidence always
    cites the original, never our copy.
    """

    claim_id: Annotated[str | None, Field(alias="claimId")] = None
    status: Annotated[str | None, Field(alias="status")] = None
    type: Annotated[str | None, Field(alias="type")] = None
    use: Annotated[str | None, Field(alias="use")] = None
    created: Annotated[datetime | None, Field(alias="created")] = None
    currency: Annotated[str, Field(alias="currency")] = "AED"
    total: Annotated[Money | None, Field(alias="total")] = None

    patient: Annotated[Member | None, Field(alias="patient")] = None
    provider: Annotated[Provider | None, Field(alias="provider")] = None
    coverage: Annotated[Coverage | None, Field(alias="coverage")] = None
    benefit_balance: Annotated[BenefitBalance | None, Field(alias="benefitBalance")] = None
    authorization: Annotated[Authorization | None, Field(alias="authorization")] = None
    encounter: Annotated[Encounter | None, Field(alias="encounter")] = None
    attachments: Annotated[list[Attachment], Field(alias="attachments")] = Field(
        default_factory=list[Attachment]
    )
    lines: Annotated[list[ClaimLine], Field(alias="lines")] = Field(default_factory=list[ClaimLine])

    # Populated by normalization; excluded from the CEL payload.
    src: dict[str, str] = Field(default_factory=dict, exclude=True)
    envelope_errors: list[str] = Field(default_factory=list, exclude=True)

    @property
    def anchor_date(self) -> date | None:
        """The date every coverage/authorization rule compares against.

        Derived as the earliest service date across lines, so a claim spanning
        several days has one unambiguous anchor.
        """
        candidates: list[date] = []
        for line in self.lines:
            if line.serviced_date:
                candidates.append(line.serviced_date)
            elif line.serviced_period_start:
                candidates.append(line.serviced_period_start)
        return min(candidates) if candidates else None


# ---------------------------------------------------------------------------
# Density helper — defined after the models it references.
# ---------------------------------------------------------------------------

# Nested models that must remain navigable in CEL even when absent.
DENSE_NULL_MODELS: tuple[type[CanonicalBase], ...] = (
    Member,
    Provider,
    Coverage,
    BenefitBalance,
    Authorization,
    Encounter,
    Money,
)


def _densify_nested(payload: dict[str, Any], model: type[CanonicalBase]) -> dict[str, Any]:
    """Replace absent nested models with null-filled objects of the same shape.

    CEL needs to traverse `payload.authorization.validFrom` even when there is no
    authorization. `None` is not traversable; a dict of nulls is. Without this, a
    rule reading a field of an absent object yields null, does not fire, and a
    genuine defect is missed — the same silent failure class as P0-1.
    """
    for field_name, field in model.model_fields.items():
        alias = field.alias or field_name
        if payload.get(alias) is not None:
            continue

        annotation = field.annotation
        # Unwrap Optional[X] / X | None
        for candidate in getattr(annotation, "__args__", ()):
            if isinstance(candidate, type) and issubclass(candidate, CanonicalBase):
                annotation = candidate
                break

        if isinstance(annotation, type) and annotation in DENSE_NULL_MODELS:
            payload[alias] = {
                (f.alias or fname): None for fname, f in annotation.model_fields.items()
            }
    return payload
