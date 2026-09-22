"""Pack transport contracts for the ClaimGuard teaching benchmark (CSTAM-VELODOC).

Source of truth — the mentor pack, read-only:
  ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/
    docs/03_Data_Dictionary.md            (field tables, result contract)
    docs/04_Rulebook.md:7-17              (shared evaluation conventions)
    schemas/claim.schema.json             (17-key envelope)
    schemas/result.schema.json            (15-key result record)
    src/engine_core.py::validate_transport (the supplied reference validator)

Two deliberate design points:

*   ``validate_transport`` mirrors the pack validator: exact key sets, non-empty
    required strings, ISO dates, unique ``line_id`` values, numeric (non-bool)
    line amounts, and the documented child-record shapes. A claim that fails it
    is an ingestion error — quarantine and report it, never repair it
    (docs/03_Data_Dictionary.md, "Nulls, keys and transport errors").

*   Rule evaluation reads the ORIGINAL parsed JSON object, never a re-coerced
    model. ``ClaimEnvelope`` is a typed gate; evidence pointers are resolved
    against the raw object so the observed value is the submitted value
    (docs/04_Rulebook.md:15 — "Evidence is a JSON pointer into the original
    normalized claim plus the exact observed value").
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict, model_validator

# ---------------------------------------------------------------------------
# Contract constants (docs/03_Data_Dictionary.md; schemas/*.json)
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "1.0.0"
RULE_VERSION: Final = "1.0.0"
RULE_IDS: Final = tuple(f"R{i:03d}" for i in range(1, 16))
RULE_SOURCE_PREFIX: Final = "fictional-rulebook/"

ENVELOPE_KEYS: Final = (
    "schema_version",
    "claim_id",
    "invoice_number",
    "patient_id",
    "member_id",
    "provider_id",
    "payer_id",
    "policy_id",
    "diagnosis_code",
    "submission_date",
    "currency",
    "total_amount",
    "coverage",
    "lines",
    "authorizations",
    "attachments",
    "notes",
)
COVERAGE_KEYS: Final = (
    "coverage_id",
    "status",
    "beneficiary_patient_id",
    "member_id",
    "start_date",
    "end_date",
)
LINE_KEYS: Final = (
    "line_id",
    "service_code",
    "service_date",
    "modifier",
    "quantity",
    "unit_price",
    "net_amount",
    "authorization_id",
)
AUTHORIZATION_KEYS: Final = (
    "authorization_id",
    "patient_id",
    "service_code",
    "status",
    "valid_from",
    "valid_to",
    "max_quantity",
)
ATTACHMENT_KEYS: Final = (
    "attachment_id",
    "type",
    "patient_id",
    "service_code",
    "service_date",
    "document_status",
    "text",
)
RESULT_KEYS: Final = (
    "claim_id",
    "rule_id",
    "rule_version",
    "status",
    "severity",
    "affected_line_ids",
    "evidence",
    "rule_source",
    "explanation",
    "corrective_action",
    "confidence",
    "confidence_kind",
    "requires_human_review",
    "method",
    "review_status",
)
EVIDENCE_KEYS: Final = ("path", "value")

#: Inclusive money tolerance in SAR (docs/04_Rulebook.md:14).
MONEY_TOLERANCE: Final = Decimal("0.01")
MONEY_QUANTUM: Final = Decimal("0.01")

#: Rule evaluation reads the raw parsed envelope; the typed model is the gate.
Claim = Mapping[str, Any]
Result = dict[str, Any]


class Status(StrEnum):
    """Result status (schemas/result.schema.json)."""

    PASS = "PASS"  # noqa: S105 - a rule status, not a credential
    FAIL = "FAIL"
    UNABLE_TO_ASSESS = "UNABLE_TO_ASSESS"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class Severity(StrEnum):
    """Result severity; fixed by the rule manifest, never by a model."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConfidenceKind(StrEnum):
    """Deterministic checks are not probabilistic (docs/04_Rulebook.md:17)."""

    NOT_PROBABILISTIC = "not_probabilistic"
    UNCALIBRATED = "uncalibrated"
    CALIBRATED = "calibrated"


class TransportError(ValueError):
    """A claim envelope violates the pack transport contract."""


class ContractError(ValueError):
    """A result record violates the frozen 15-key result contract."""


@dataclass(frozen=True)
class IngestionError:
    """One quarantined input line: a transport defect, reported, never dropped.

    docs/03_Data_Dictionary.md ("Nulls, keys and transport errors"): a malformed
    JSON line, a wrong structural type, a duplicate line ID or a missing
    transport key is an *ingestion error* — quarantine it and report it
    separately, never silently drop it or create a passed claim.
    """

    line_number: int
    claim_id: str | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        """Structured form for logs and sidecar reports."""
        return {
            "line_number": self.line_number,
            "claim_id": self.claim_id,
            "reason": self.reason,
            "kind": "ingestion_error",
        }

    def __str__(self) -> str:
        return f"line {self.line_number} claim_id={self.claim_id!r}: {self.reason}"


# ---------------------------------------------------------------------------
# Value interpretation helpers
#
# These encode the shared evaluation conventions (docs/04_Rulebook.md:7-17):
# missing means null or blank, dates are day-precision, money is Decimal with
# ROUND_HALF_UP, and identifiers are compared exactly (never trimmed/repaired).
# ---------------------------------------------------------------------------


def is_empty(value: Any) -> bool:
    """True for null or blank strings — a *known absence* in the pack's sense."""
    return value is None or (isinstance(value, str) and not value.strip())


def is_number(value: Any) -> bool:
    """True for JSON numbers. ``bool`` is not a number here (it is not a quantity)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_iso_date(value: Any) -> date | None:
    """Parse an ISO date at day precision, or return None when unusable."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def to_decimal(value: Any) -> Decimal:
    """Convert a JSON number to Decimal through its string form (never binary float)."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:  # pragma: no cover - transport guards types
        raise ContractError(f"not a decimal number: {value!r}") from exc


def money(value: Any) -> Decimal:
    """Round a money amount to 2 decimal places using ROUND_HALF_UP."""
    return to_decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def is_positive_integer(value: Any) -> bool:
    """True for a positive whole number (R013; docs/04_Rulebook.md:136-142).

    ``1.5`` and ``-1`` fail; ``2`` and ``2.0`` pass. The supplied splits only
    exercise ``1.5``/``-1``, so the rulebook's plain reading is what is coded
    here: "Every quantity must be a positive integer".
    """
    if not is_number(value):
        return False
    number = to_decimal(value)
    return number > 0 and number == number.to_integral_value()


def in_range(day: date, start: date | None, end: date | None) -> bool:
    """Inclusive day-precision range test (docs/04_Rulebook.md:14)."""
    if start is not None and day < start:
        return False
    return not (end is not None and day > end)


# ---------------------------------------------------------------------------
# Envelope models (schemas/claim.schema.json)
# ---------------------------------------------------------------------------


class Coverage(BaseModel):
    """Supplied coverage record; comparison fields may be null (docs/03)."""

    coverage_id: str | None = None
    status: str | None = None
    beneficiary_patient_id: str | None = None
    member_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class Line(BaseModel):
    """Service line; business fields may be null to represent omissions."""

    line_id: str
    service_code: str | None = None
    service_date: str | None = None
    modifier: str | None = None
    quantity: int | float | None = None
    unit_price: int | float | None = None
    net_amount: int | float | None = None
    authorization_id: str | None = None


class Authorization(BaseModel):
    """Authorization sidecar record; the reference itself is line-level."""

    authorization_id: str
    patient_id: str | None = None
    service_code: str | None = None
    status: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    max_quantity: int | float | None = None


class Attachment(BaseModel):
    """Attachment inventory entry; ``text`` is untrusted content (docs/03)."""

    attachment_id: str
    type: str | None = None
    patient_id: str | None = None
    service_code: str | None = None
    service_date: str | None = None
    document_status: str | None = None
    text: str | None = None


class ClaimEnvelope(BaseModel):
    """The 17-key normalized claim envelope of the teaching contract."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    claim_id: str
    invoice_number: str | None = None
    patient_id: str
    member_id: str | None = None
    provider_id: str
    payer_id: str
    policy_id: str
    diagnosis_code: str | None = None
    submission_date: str
    currency: str
    total_amount: int | float | None = None
    coverage: Coverage
    lines: list[Line]
    authorizations: list[Authorization]
    attachments: list[Attachment]
    notes: str


def validate_transport(raw: Mapping[str, Any]) -> ClaimEnvelope:
    """Validate one claim envelope, mirroring the pack's ``validate_transport``.

    Raises :class:`TransportError` on any transport defect. Structural keys are
    required; nullable business values are deliberately permitted even when a
    payer rule demands them (docs/03_Data_Dictionary.md).
    """
    if not isinstance(raw, dict):
        raise TransportError("Claim must be a JSON object")
    if set(raw) != set(ENVELOPE_KEYS):
        raise TransportError("Unexpected or missing envelope keys")

    for key in (
        "schema_version",
        "claim_id",
        "patient_id",
        "provider_id",
        "payer_id",
        "policy_id",
        "submission_date",
        "currency",
        "notes",
    ):
        if not isinstance(raw[key], str) or not raw[key]:
            raise TransportError(f"Expected nonempty string: {key}")
    for key in ("invoice_number", "member_id", "diagnosis_code"):
        if raw[key] is not None and not isinstance(raw[key], str):
            raise TransportError(f"Expected string or null: {key}")
    if parse_iso_date(raw["submission_date"]) is None:
        raise TransportError("Invalid submission date")

    lines = raw["lines"]
    if not isinstance(lines, list) or not lines:
        raise TransportError("Expected nonempty lines")
    seen_ids: set[str] = set()
    for entry in cast(list[object], lines):
        if not isinstance(entry, dict):
            raise TransportError("Line keys must match the transport contract")
        line = cast(dict[str, Any], entry)
        if set(line) != set(LINE_KEYS):
            raise TransportError("Line keys must match the transport contract")
        if not isinstance(line["line_id"], str) or not line["line_id"]:
            raise TransportError("line_id must be a nonempty string")
        if line["line_id"] in seen_ids:
            raise TransportError("Duplicate line ID")
        seen_ids.add(line["line_id"])
        for key in ("service_code", "service_date", "modifier", "authorization_id"):
            if line[key] is not None and not isinstance(line[key], str):
                raise TransportError(f"Expected string or null: lines[].{key}")
        if line["service_date"] is not None and parse_iso_date(line["service_date"]) is None:
            raise TransportError("Invalid service date")
        for key in ("quantity", "unit_price", "net_amount"):
            if line[key] is not None and not is_number(line[key]):
                raise TransportError(f"Expected number or null: lines[].{key}")

    coverage = raw["coverage"]
    if not isinstance(coverage, dict):
        raise TransportError("Coverage keys must match the transport contract")
    coverage_record = cast(dict[str, Any], coverage)
    if set(coverage_record) != set(COVERAGE_KEYS):
        raise TransportError("Coverage keys must match the transport contract")
    for key in COVERAGE_KEYS:
        value = coverage_record[key]
        if value is not None and not isinstance(value, str):
            raise TransportError(f"Expected string or null: coverage.{key}")

    if raw["total_amount"] is not None and not is_number(raw["total_amount"]):
        raise TransportError("Expected number or null: total_amount")

    _validate_child_records(
        raw["authorizations"], AUTHORIZATION_KEYS, ("max_quantity",), "authorization"
    )
    _validate_child_records(raw["attachments"], ATTACHMENT_KEYS, (), "attachment")

    try:
        return ClaimEnvelope.model_validate(dict(raw), strict=False)
    except ValueError as exc:  # pragma: no cover - the checks above cover every field
        raise TransportError(f"Envelope failed model validation: {exc}") from exc


def _validate_child_records(
    records: Any, keys: tuple[str, ...], numeric_keys: tuple[str, ...], label: str
) -> None:
    """Validate the documented shape of an authorizations/attachments inventory."""
    if not isinstance(records, list):
        raise TransportError(f"Expected a list of {label} records")
    for entry in cast(list[object], records):
        if not isinstance(entry, dict):
            raise TransportError(f"{label.capitalize()} keys must match the transport contract")
        record = cast(dict[str, Any], entry)
        if set(record) != set(keys):
            raise TransportError(f"{label.capitalize()} keys must match the transport contract")
        for key, value in record.items():
            if value is None or key in numeric_keys:
                continue
            if not isinstance(value, str):
                raise TransportError(f"Expected string or null: {label}.{key}")
        for key in numeric_keys:
            if record[key] is not None and not is_number(record[key]):
                raise TransportError(f"Expected number or null: {label}.{key}")


# ---------------------------------------------------------------------------
# Result record model (schemas/result.schema.json)
# ---------------------------------------------------------------------------


class EvidenceEntry(BaseModel):
    """One evidence pointer plus the exact value observed at that path."""

    model_config = ConfigDict(extra="forbid")

    path: str
    value: Any


class ResultRecord(BaseModel):
    """One claim-rule result: exactly the 15 keys of the frozen contract."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    rule_id: str
    rule_version: str
    status: Status
    severity: Severity
    affected_line_ids: list[str]
    evidence: list[EvidenceEntry]
    rule_source: str
    explanation: str
    corrective_action: str
    confidence: float | None = None
    confidence_kind: ConfidenceKind
    requires_human_review: bool
    method: str
    review_status: str

    @model_validator(mode="after")
    def _check_contract(self) -> ResultRecord:
        """Enforce the pack's per-record invariants (docs/07, src/evaluate.py::index)."""
        if self.rule_id not in RULE_IDS:
            raise ValueError(f"Unknown rule: {self.rule_id}")
        if self.rule_version != RULE_VERSION:
            raise ValueError("rule_version must be 1.0.0")
        if self.rule_source != f"{RULE_SOURCE_PREFIX}{self.rule_id}@{RULE_VERSION}":
            raise ValueError("Unknown rule source")
        if self.status is not Status.NOT_IMPLEMENTED and not self.evidence:
            raise ValueError("Evidence is required for every implemented status")
        if self.status in (Status.FAIL, Status.UNABLE_TO_ASSESS):
            if not self.requires_human_review:
                raise ValueError("FAIL and UNABLE_TO_ASSESS require human review")
            if not self.corrective_action.strip():
                raise ValueError("FAIL and UNABLE_TO_ASSESS require a corrective action")
        if self.confidence_kind is ConfidenceKind.NOT_PROBABILISTIC and self.confidence is not None:
            raise ValueError("Deterministic confidence must be null")
        if not self.explanation.strip():
            raise ValueError("Explanation is required")
        if self.method != "deterministic" or self.review_status != "unreviewed":
            raise ValueError("Engine results are deterministic and unreviewed")
        for entry in self.evidence:
            if not entry.path.startswith("/"):
                raise ValueError(f"Evidence needs a JSON pointer: {entry.path!r}")
        return self


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Load a JSONL file into parsed JSON objects (blank lines are skipped)."""
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def load_transport_claims(
    path: str | Path,
) -> tuple[list[dict[str, Any]], list[IngestionError]]:
    """Parse and validate a claim file, quarantining defective lines.

    Returns ``(accepted, quarantined)``: every input line is accounted for
    exactly once, so a defective claim can never reach the engine (and therefore
    can never be emitted as a passed claim) and is never silently dropped.
    """
    accepted: list[dict[str, Any]] = []
    quarantined: list[IngestionError] = []
    text = Path(path).read_text(encoding="utf-8")
    for line_number, text_line in enumerate(text.splitlines(), start=1):
        if not text_line.strip():
            continue
        try:
            parsed: Any = json.loads(text_line)
        except json.JSONDecodeError as exc:
            quarantined.append(
                IngestionError(line_number, None, f"malformed JSON: {exc.msg} (column {exc.colno})")
            )
            continue
        if not isinstance(parsed, dict):
            quarantined.append(
                IngestionError(line_number, None, "malformed envelope: expected a JSON object")
            )
            continue
        claim = cast(dict[str, Any], parsed)
        raw_id = claim.get("claim_id")
        claim_id = raw_id if isinstance(raw_id, str) and raw_id else None
        try:
            validate_transport(claim)
        except TransportError as exc:
            quarantined.append(IngestionError(line_number, claim_id, str(exc)))
            continue
        accepted.append(claim)
    return accepted, quarantined


def write_jsonl(path: str | Path, lines: list[str]) -> None:
    """Write pre-serialized JSONL, creating the parent directory when needed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
