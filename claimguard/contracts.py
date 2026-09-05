"""Output contracts for ClaimGuard AI.

These Pydantic models are the contract between:
  - the deterministic rule engine,
  - the LLM enrichment layer,
  - the API layer, and
  - the reviewer UI.

They are the Phase-1 "explainability & structured output" scoring surface (10 pts):
every Finding MUST carry claim_id, rule_id, rule-linked evidence, severity,
confidence, and a suggested corrective action.

Design rule (see 04 §6 / 09 §Part B): the LLM may write *language* here. It may
never decide *outcomes*. Every structured field below is produced by deterministic
code; the LLM only fills `ExplanationStep.text` and may rephrase narrative strings.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SignalFamily(StrEnum):
    """The six signal families.

    For the 12 fixture-backed rules these come from Velodoc's published fixture
    labels (authoritative — see 03 §2.2 and 09 §Part B P1-4). For our own ADDED
    rules with no fixture, the YAML manifest is the source of truth.
    """

    COVERAGE = "Coverage"
    AUTHORIZATION = "Authorization"
    INTEGRITY = "Integrity"
    IDENTITY = "Identity"
    DOCUMENTATION = "Documentation"
    CLEAN = "Clean"


class Severity(StrEnum):
    """Finding severity.

    Set by the rule manifest only. The LLM may NEVER set or change severity —
    that is a hard invariant enforced by the verifier (LLM-05).
    """

    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class Tone(StrEnum):
    """Display tone, matching Velodoc's own Claim Lab (red / amber)."""

    RED = "red"
    AMBER = "amber"
    NEUTRAL = "neutral"


class EmitResult(StrEnum):
    """Outcome of an evidence-verified emission.

    P1-6 fix (see 09 §Part B): emit() must never drop a finding silently.
    """

    EMITTED = "emitted"
    SUPPRESSED = "suppressed"
    DEFERRED_TO_HITL = "deferred_to_hitl"


class ReviewTier(StrEnum):
    """Three-tier reviewer routing."""

    T1_STANDARD = "T1"
    T2_POLICY = "T2"
    T3_COMPLIANCE = "T3"


class OverrideOutcome(StrEnum):
    UPHELD = "upheld"
    OVERRIDE_RULE = "override_rule"
    OVERRIDE_SEVERITY = "override_severity"
    ESCALATE_HIGHER = "escalate_higher"


class OverrideReasonCode(StrEnum):
    """Structured reason codes — overrides are never free text.

    Free text is allowed only as an optional short note. Reason CODES are what
    make overrides auditable and aggregateable (04 §5).
    """

    THRESHOLD_WRONG = "threshold_wrong"
    RULE_NOT_APPLICABLE = "rule_not_applicable"
    MISSING_CONTEXT = "missing_context"
    MEMBER_SPECIFIC = "member_specific"
    POLICY_CHANGE = "policy_change"
    EVIDENCE_POINTER_FAILURE = "evidence_pointer_failure"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    """One piece of proof behind a finding.

    `json_pointer` is an RFC 6901 pointer into the ORIGINAL claim package, and it
    MUST resolve. A finding whose pointers do not resolve is not emitted — that is
    the evidence-first invariant (05 §3).
    """

    model_config = ConfigDict(frozen=True)

    json_pointer: str = Field(
        description="RFC 6901 pointer into the original claim package, e.g. /item/0/net",
    )
    rule_id: str = Field(description="Rule this evidence supports.")
    value_snapshot: str | None = Field(
        default=None,
        description=(
            "The resolved value at emit time. Stored so an audit can be reconstructed "
            "without re-reading the package. Redacted if the field carried PII."
        ),
    )
    derived: bool = Field(
        default=False,
        description=(
            "True when this evidence proves an ABSENCE (the pointer resolves to a null "
            "node) or a computed value, rather than a literal field. See 05 §9.3."
        ),
    )

    @field_validator("json_pointer")
    @classmethod
    def _pointer_must_be_absolute(cls, v: str) -> str:
        if not v:
            msg = "json_pointer must not be empty"
            raise ValueError(msg)
        if not v.startswith("/"):
            msg = f"json_pointer must be an absolute RFC 6901 pointer starting with '/': {v!r}"
            raise ValueError(msg)
        return v


class ExplanationStep(BaseModel):
    """One verifiable sentence of the narrative.

    Every step cites at least one evidence pointer. A step whose citations do not
    resolve is dropped or marked unsupported by the verifier (LLM-05) — it is never
    shown to a reviewer as fact.
    """

    text: str = Field(description="One claim about the finding, in reviewer-facing language.")
    evidence_pointers: list[str] = Field(
        min_length=1,
        description="Pointers proving this step. Must all resolve.",
    )


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    """A validation finding — the core scored output artifact.

    The six Phase-1 scored fields are: claim_id, rule_id, evidence (rule-linked),
    severity, confidence, suggested_action. All are mandatory.
    """

    model_config = ConfigDict(frozen=True)

    finding_id: str = Field(description="Stable id for this finding instance.")
    claim_id: str = Field(description="The claim package identifier (CLM-xxxx).")

    rule_id: str = Field(description="Rule identifier, e.g. COV-001.")
    rule_version: int = Field(
        ge=1,
        description=(
            "Version of the rule that fired. Audit requires knowing exactly which "
            "rule text produced this finding (05 §4)."
        ),
    )
    rule_family: SignalFamily
    rule_name: str

    severity: Severity
    tone: Tone
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Deterministic rules are 1.0 by definition. Values < 1.0 appear only for "
            "LLM-derived artifacts (normalization, explanation). See 04 §7."
        ),
    )

    title: str = Field(description="Short human-readable summary.")
    detail: str = Field(description="Why this fired, in reviewer-facing language.")

    evidence: list[Evidence] = Field(
        min_length=1,
        description="At least one resolving pointer. Enforced at emit time.",
    )
    suggested_action: str = Field(
        description="The corrective or investigative next step for the reviewer.",
    )

    explanation: Annotated[
        list[ExplanationStep],
        Field(
            default_factory=list,
            description="Optional narrative. Verified pointer-by-pointer before display.",
        ),
    ]
    mandatory_escalation: bool = Field(
        default=False,
        description=(
            "True for topics that route to a human regardless of confidence "
            "(AUTH-004/006/009, ENC-001, eligibility/benefit). See 04 §5."
        ),
    )
    payer: str | None = Field(default=None, description="Payer code if from a policy pack.")
    pack_version: str | None = Field(default=None, description="Policy pack version, if any.")
    source_url: str | None = Field(
        default=None, description="Payer publication the rule came from, if any."
    )
    llm_unverified: bool = Field(
        default=False,
        description="True when the narrative failed verification and must not be trusted.",
    )

    @model_validator(mode="after")
    def _severity_matches_tone(self) -> Finding:
        if self.severity in (Severity.HIGH, Severity.CRITICAL) and self.tone is Tone.NEUTRAL:
            msg = f"{self.rule_id}: severity {self.severity.value} must not display as neutral tone"
            raise ValueError(msg)
        return self


class ValidationReport(BaseModel):
    """The complete result of running the gate over one claim package."""

    report_id: str
    claim_id: str
    created_at: datetime

    quality_gate: Literal["passed", "review", "blocked"] = Field(
        description=(
            "passed = zero findings, ready to submit (NOT 'approved' — see below). "
            "review = findings exist, a human should look. "
            "blocked = ENV-001 fired, package unreadable."
        )
    )
    findings: Annotated[list[Finding], Field(default_factory=list)]

    catalogue_hash: str = Field(description="Hash of the rule catalogue version used.")
    trace_id: str = Field(description="OpenTelemetry trace id for the whole run.")
    suppressed_count: int = Field(
        default=0,
        description=(
            "Findings that fired but whose evidence failed to resolve. Always recorded — "
            "never silently dropped (P1-6)."
        ),
    )

    @model_validator(mode="after")
    def _gate_matches_findings(self) -> ValidationReport:
        if self.quality_gate == "passed" and self.findings:
            msg = "quality_gate='passed' is inconsistent with non-empty findings"
            raise ValueError(msg)
        return self


# ---------------------------------------------------------------------------
# Review / audit
# ---------------------------------------------------------------------------


class OverrideDecision(BaseModel):
    """A reviewer's decision. Structured reason code required."""

    task_id: str
    reviewer_id: str
    outcome: OverrideOutcome
    reason_code: OverrideReasonCode
    note: str | None = Field(default=None, max_length=500)
    decided_at: datetime


class AuditEvent(BaseModel):
    """One append-only audit entry.

    Storage rule (04 §9): enough to reconstruct, never enough to leak. Opaque ids
    and pointers only — never diagnosis text or patient narrative.
    """

    event_id: str
    at: datetime
    kind: Literal[
        "claim.received",
        "claim.normalized",
        "rule.evaluated",
        "finding.emitted",
        "finding.suppressed",
        "llm.called",
        "route.decided",
        "review.decided",
        "catalogue.changed",
        "error",
    ]
    claim_ref: str | None = None
    trace_id: str
    decision: str | None = None
    reason_code: str | None = None
    finding_ids: list[str] = Field(default_factory=list)
    rule_version: str | None = None
    model_version: str | None = None
    prev_hash: str = Field(description="Hash of the previous event; 'genesis' for the first.")
    chain_hash: str = Field(description="SHA-256 of this event; see 05 §4 trigger.")


class Money(BaseModel):
    """Monetary amount. Decimal, never float — money must not round silently."""

    model_config = ConfigDict(frozen=True)

    value: Decimal
    currency: str = Field(default="AED", min_length=3, max_length=3)

    def __str__(self) -> str:
        return f"{self.value} {self.currency}"
