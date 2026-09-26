"""Reviewer-workflow contracts for the ClaimGuard review surface (MVP behaviours 4, 5, 7).

WHAT THIS MODULE IS
-------------------
The three shapes the reviewer surface exchanges, plus the small state machine
that governs them:

*   :class:`RuleRun` — one immutable engine run over one claim version. It binds
    a claim version to the versions of everything that produced its results (rule
    catalogue, model, prompt), which is required behaviour 7 of
    ``docs/01_Challenge_Brief.md``.
*   :class:`FindingView` — one of the run's 15 records (the frozen 15-key pack
    contract, validated by :class:`claimguard.edu.envelope.ResultRecord`) plus the
    reviewer's current status for that finding.
*   :class:`ReviewDecisionEvent` — exactly the pack's 7-key review event
    (``schemas/review_event.schema.json``: seven required keys,
    ``additionalProperties: false``).

WHAT THIS MODULE IS NOT
-----------------------
It is not a second copy of the result contract. The 15-key record is validated by
the engine's own model, so the reviewer surface cannot drift from what the pack's
scorer reads. Nothing here approves, denies, pays or adjudicates anything: a
review decision is a reviewer's note *about a check*, and the check's own status
is immutable (a correction is a new claim version, never an edit).

THE ONE CONTRACT JUDGEMENT CALL
-------------------------------
``review_event.original_status`` is the **rule status of the finding at the time
of the decision** (``FAIL``, ``UNABLE_TO_ASSESS``, ...), not the reviewer's
status. That is what the pack's own review page records — ``examples/
review_demo.html`` builds the event as ``{..., original_status: r.status}`` where
``r`` is the 15-key result record — and it is the value that lets a decision be
replayed against the check it is about. A status that does not match the stored
result is rejected by the store rather than silently accepted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from claimguard.edu.envelope import RULE_IDS, ResultRecord, Severity, Status
from claimguard.edu.explain import SOURCE_DETERMINISTIC, SOURCE_MODEL

# ---------------------------------------------------------------------------
# Contract constants (mirrors schemas/review_event.schema.json)
# ---------------------------------------------------------------------------

#: The pack's review event keys, in the pack's own order.
REVIEW_EVENT_KEYS: Final[tuple[str, ...]] = (
    "claim_id",
    "rule_id",
    "action",
    "actor",
    "reason",
    "created_at",
    "original_status",
)

#: ``run_id`` format: opaque, prefixed, no claim identifier inside it.
RUN_ID_PREFIX: Final = "RUN-"
TRACE_HEX_LENGTH: Final = 32

_HASH_PATTERN: Final = r"^[0-9a-f]{64}$"


class ReviewAction(StrEnum):
    """The four review actions the pack allows — and only these four."""

    CONFIRM_ISSUE = "confirm_issue"
    DISMISS_WITH_REASON = "dismiss_with_reason"
    REQUEST_INFORMATION = "request_information"
    MARK_CORRECTED_FOR_RECHECK = "mark_corrected_for_recheck"


class ReviewStatus(StrEnum):
    """The reviewer's current status for one finding on one run version.

    Deliberately *not* the pack's ``result.review_status`` (which the frozen
    contract fixes at ``unreviewed`` for engine output): this is the review
    surface's own state, derived from the append-only decision history.
    """

    UNREVIEWED = "unreviewed"
    INFO_REQUESTED = "info_requested"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    CORRECTED_FOR_RECHECK = "corrected_for_recheck"


REVIEW_ACTIONS: Final[tuple[str, ...]] = tuple(action.value for action in ReviewAction)
REVIEW_STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in ReviewStatus)

#: The status a decision moves a finding to.
ACTION_STATUS: Final[Mapping[ReviewAction, ReviewStatus]] = {
    ReviewAction.CONFIRM_ISSUE: ReviewStatus.CONFIRMED,
    ReviewAction.DISMISS_WITH_REASON: ReviewStatus.DISMISSED,
    ReviewAction.REQUEST_INFORMATION: ReviewStatus.INFO_REQUESTED,
    ReviewAction.MARK_CORRECTED_FOR_RECHECK: ReviewStatus.CORRECTED_FOR_RECHECK,
}

#: Statuses that still owe the reviewer work: the check has not been looked at,
#: or the reviewer asked a question and is waiting for the answer.
UNRESOLVED_STATUSES: Final[frozenset[ReviewStatus]] = frozenset(
    {ReviewStatus.UNREVIEWED, ReviewStatus.INFO_REQUESTED}
)

#: The decision state machine.
#:
#: *   An unreviewed or reopened (``info_requested``) finding accepts any action.
#: *   A decided finding (``confirmed``/``dismissed``) accepts only *reopening*
#:     (``request_information``) or ``mark_corrected_for_recheck``. Repeating the
#:     same terminal action is rejected: it adds a row to an append-only ledger
#:     without changing the reviewer's answer, and the reviewer who wants to say
#:     "still confirmed, new information arrived" has ``request_information``.
#: *   ``corrected_for_recheck`` is terminal on that run version. The correction
#:     produces a new run, and the open questions live on the new version's
#:     findings — never on the superseded one.
ALLOWED_TRANSITIONS: Final[Mapping[ReviewStatus, frozenset[ReviewAction]]] = {
    ReviewStatus.UNREVIEWED: frozenset(ReviewAction),
    ReviewStatus.INFO_REQUESTED: frozenset(ReviewAction),
    ReviewStatus.CONFIRMED: frozenset(
        {ReviewAction.REQUEST_INFORMATION, ReviewAction.MARK_CORRECTED_FOR_RECHECK}
    ),
    ReviewStatus.DISMISSED: frozenset(
        {ReviewAction.REQUEST_INFORMATION, ReviewAction.MARK_CORRECTED_FOR_RECHECK}
    ),
    ReviewStatus.CORRECTED_FOR_RECHECK: frozenset(),
}


class IllegalReviewTransitionError(ValueError):
    """The action is not allowed from the finding's current review status."""


def next_status(current: ReviewStatus, action: ReviewAction) -> ReviewStatus:
    """Apply the decision state machine; raise :class:`IllegalReviewTransitionError`."""
    allowed = ALLOWED_TRANSITIONS[current]
    if action not in allowed:
        raise IllegalReviewTransitionError(
            f"{action.value} is not allowed from review status {current.value!r}"
            + ("" if allowed else " (this run version is superseded; decide on the recheck run)")
        )
    return ACTION_STATUS[action]


def is_unresolved(status: ReviewStatus) -> bool:
    """True while the reviewer still owes this finding an answer."""
    return status in UNRESOLVED_STATUSES


def requires_attention(record: ResultRecord) -> bool:
    """True when a check must be visible in the review queue.

    Two independent reasons, both grounded in the pack:

    *   the record asks for human review — the engine sets
        ``requires_human_review`` for ``FAIL`` and ``UNABLE_TO_ASSESS``;
    *   the check never ran (``NOT_IMPLEMENTED``). The pack's review page tells
        the reviewer "this check has not run. The claim cannot be considered
        fully checked", so an unimplemented check can never be filtered away as
        if it were clean (``docs/07_Evaluation_and_Acceptance.md``: "No
        unimplemented or unknown check is represented as a pass").
    """
    return record.requires_human_review or record.status is Status.NOT_IMPLEMENTED


def _aware(value: datetime) -> datetime:
    """Require a timezone-aware timestamp.

    All stored timestamps are UTC (the store pins ``TimeZone=UTC``, which the
    audit hash chain depends on), and an aware timestamp is required for
    ``review_decisions.created_at`` to be rendered to the pack's ISO string
    without inventing an offset.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("timestamp must carry a timezone offset")
    return value


def _non_blank(value: str) -> str:
    """Reject blank text. The value is kept verbatim — reviewer input is not rewritten."""
    if not value.strip():
        raise ValueError("must not be blank")
    return value


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class RuleRun(BaseModel):
    """One immutable engine run over one version of one claim.

    ``version`` starts at 1 and increases by one per correction; a recheck run
    points at the run it replaces through ``supersedes_run_id``. The submitted
    envelope is never part of this model (it lives in the store, byte-identical,
    for replay) — a reviewer reads evidence pointers into it, not a copy of it.
    ``initiated_by`` names who asked for the run: the submission surface
    (``api-submit``) or the reviewer who requested a recheck.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    claim_id: str
    version: int = Field(ge=1)
    input_hash: str = Field(pattern=_HASH_PATTERN)
    trace_id: str = Field(min_length=TRACE_HEX_LENGTH, max_length=TRACE_HEX_LENGTH)
    rule_version: str
    model_version: str
    prompt_version: str
    initiated_by: str
    created_at: datetime
    supersedes_run_id: str | None = None

    @field_validator(
        "run_id",
        "claim_id",
        "rule_version",
        "model_version",
        "prompt_version",
        "initiated_by",
    )
    @classmethod
    def _text_is_present(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        return _aware(value)


# ---------------------------------------------------------------------------
# Review state and finding views
# ---------------------------------------------------------------------------


class ReviewState(BaseModel):
    """The reviewer's current status for one finding, derived from its decisions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ReviewStatus = ReviewStatus.UNREVIEWED
    action: ReviewAction | None = None
    actor: str | None = None
    reason: str | None = None
    decided_at: datetime | None = None
    decision_count: int = Field(default=0, ge=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unresolved(self) -> bool:
        """True while the check still owes the reviewer an answer."""
        return is_unresolved(self.status)


class FindingView(BaseModel):
    """One of a run's 15 records plus the reviewer's current status for it.

    ``record`` is the frozen 15-key engine record, validated by the engine's own
    model (``ResultRecord``): the reviewer surface adds state beside it and never
    rewrites it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    claim_id: str
    version: int = Field(ge=1)
    run_created_at: datetime
    record: ResultRecord
    review: ReviewState = Field(default_factory=ReviewState)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def needs_attention(self) -> bool:
        """True when this check belongs in the review queue (see requires_attention)."""
        return requires_attention(self.record)


class ClaimQueueSummary(BaseModel):
    """Per-claim rollup of the queue: the unresolved-check count, stated plainly."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str
    run_id: str
    version: int = Field(ge=1)
    findings: int = Field(ge=0)
    unresolved: int = Field(ge=0)
    latest_decision_at: datetime | None = None


#: Provenance sources an explanation can declare (the explain layer's own markers).
EXPLANATION_SOURCES: Final[tuple[str, ...]] = (SOURCE_DETERMINISTIC, SOURCE_MODEL)
SECURITY_DECISIONS: Final[tuple[str, ...]] = ("accept", "fallback", "decline", "unrecorded")


class ExplanationProvenance(BaseModel):
    """How one record's reviewer-facing explanation was produced.

    This is the *provenance* of the wording, never a statement about the check:
    the status, severity and evidence of the record it belongs to came from the
    deterministic engine and are unchanged by anything recorded here. It travels
    beside the 15-key record (``RunResultsResponse.explanations``, one entry per
    record, in R001..R015 order) because the frozen result contract forbids a
    sixteenth key.

    ``source`` is the provenance the provider declared (``deterministic`` when no
    model was used), ``rewritten`` says whether the record's ``explanation`` was
    replaced by this layer, ``fallback_used`` says the deterministic text stands
    because the model path did not deliver, and ``rejection_reasons`` /
    ``declined_reason`` say why — so a reviewer can tell model-assisted wording
    from deterministic text without trusting a marker inside the text itself.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    seq: int = Field(ge=1, le=15)
    source: str
    provider: str
    rewritten: bool
    fallback_used: bool
    correction_recommendation: str
    cited_evidence_paths: list[str] = Field(default_factory=list)
    security_decision: str
    receipt_sha256: str | None = Field(default=None, pattern=_HASH_PATTERN)
    rejection_reasons: list[str] = Field(default_factory=list)
    declined_reason: str | None = None

    @field_validator("rule_id")
    @classmethod
    def _rule_is_known(cls, value: str) -> str:
        if value not in RULE_IDS:
            raise ValueError(f"unknown rule id: {value!r}")
        return value

    @field_validator("source")
    @classmethod
    def _source_is_known(cls, value: str) -> str:
        if value not in EXPLANATION_SOURCES:
            raise ValueError(f"unknown explanation source: {value!r}")
        return value

    @field_validator("provider")
    @classmethod
    def _provider_is_present(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("correction_recommendation")
    @classmethod
    def _recommendation_is_present(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("security_decision")
    @classmethod
    def _security_decision_is_known(cls, value: str) -> str:
        if value not in SECURITY_DECISIONS:
            raise ValueError(f"unknown assistance security decision: {value!r}")
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def model_assisted(self) -> bool:
        """True when a model drafted the text the reviewer is reading."""
        return self.source == SOURCE_MODEL


class QueueFilters(BaseModel):
    """The filters that produced a queue listing (echoed, so a reviewer can see them)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Status | None = None
    severity: Severity | None = None
    rule_id: str | None = None
    claim_id: str | None = None
    include_all: bool = False


class QueueCounts(BaseModel):
    """Counts over the queue as returned (after filters, including attention filtering)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    findings: int = Field(ge=0)
    unresolved: int = Field(ge=0)
    resolved: int = Field(ge=0)
    by_rule_status: dict[str, int] = Field(default_factory=dict)
    by_review_status: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)


class ReviewQueue(BaseModel):
    """A filtered page of current findings with explicit unresolved-check counts.

    Counts describe the returned set, so "3 unresolved" always refers to what the
    reviewer is looking at. Queue items come from each claim's **latest** run
    version; superseded versions stay readable through the run endpoints.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    filters: QueueFilters
    counts: QueueCounts
    claims: list[ClaimQueueSummary]
    items: list[FindingView]


# ---------------------------------------------------------------------------
# Review decisions
# ---------------------------------------------------------------------------


class ReviewDecisionEvent(BaseModel):
    """Exactly the pack's 7-key review event (``schemas/review_event.schema.json``).

    ``extra="forbid"`` makes ``additionalProperties: false`` real: an eighth key
    is rejected, a missing key is rejected, an action outside the pack's four is
    rejected, and a blank ``actor`` or ``reason`` is rejected — the pack's own
    review page refuses to record a decision without both, and
    ``src/audit.py`` raises ``"Review reason is required"`` for an empty reason.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str
    rule_id: str
    action: ReviewAction
    actor: str
    reason: str
    created_at: datetime
    original_status: Status

    @field_validator("claim_id", "rule_id", "actor", "reason")
    @classmethod
    def _text_is_present(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("rule_id")
    @classmethod
    def _rule_is_known(cls, value: str) -> str:
        if value not in RULE_IDS:
            raise ValueError(f"unknown rule id: {value!r}")
        return value

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        return _aware(value)

    @classmethod
    def from_event(cls, payload: Mapping[str, Any]) -> ReviewDecisionEvent:
        """Validate one already-serialized event (the pack's transport shape)."""
        return cls.model_validate(dict(payload))

    def to_event(self) -> dict[str, Any]:
        """Render the event as JSON-ready data: exactly the pack's seven keys.

        ``created_at`` is an ISO-8601 string here because the pack's schema types
        it as a string; the model keeps it as a ``datetime`` so comparisons and
        storage cannot depend on string parsing.
        """
        return {
            "claim_id": self.claim_id,
            "rule_id": self.rule_id,
            "action": self.action.value,
            "actor": self.actor,
            "reason": self.reason,
            "created_at": self.created_at.isoformat(),
            "original_status": self.original_status.value,
        }


class StoredDecision(BaseModel):
    """A persisted decision: the pack's event plus the store's own identifiers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str
    run_id: str
    event: ReviewDecisionEvent


# ---------------------------------------------------------------------------
# Request / response models for the HTTP surface
# ---------------------------------------------------------------------------


class DecisionRequest(BaseModel):
    """A reviewer's decision, as submitted.

    Only the four fields a *client* may supply. ``claim_id``, ``original_status``
    and ``created_at`` are derived server-side from the stored run and the stored
    result (and the database clock), so a decision can never be recorded against
    a claim or a status that the engine did not produce.
    """

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    action: ReviewAction
    actor: str
    reason: str

    @field_validator("rule_id", "actor", "reason")
    @classmethod
    def _text_is_present(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("rule_id")
    @classmethod
    def _rule_is_known(cls, value: str) -> str:
        if value not in RULE_IDS:
            raise ValueError(f"unknown rule id: {value!r}")
        return value


class SubmitClaimRequest(BaseModel):
    """One claim envelope to validate and evaluate."""

    model_config = ConfigDict(extra="forbid")

    claim: dict[str, Any]


class RecheckRequest(BaseModel):
    """A corrected claim envelope, submitted as a NEW version of the claim.

    ``actor`` is required: a correction is a human action and the audit trail
    records who asked for the rerun (required behaviour 7).
    """

    model_config = ConfigDict(extra="forbid")

    claim: dict[str, Any]
    actor: str

    @field_validator("actor")
    @classmethod
    def _text_is_present(cls, value: str) -> str:
        return _non_blank(value)


class AuditStamp(BaseModel):
    """Where a write landed in the append-only audit chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    at: datetime
    kind: str
    chain_hash: str

    @field_validator("at")
    @classmethod
    def _at_is_aware(cls, value: datetime) -> datetime:
        return _aware(value)


class RunResponse(BaseModel):
    """The outcome of submitting (or rechecking) a claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: RuleRun
    results: int = Field(ge=0)
    needs_attention: int = Field(ge=0)
    by_status: dict[str, int]
    duplicate: bool = False
    audit: AuditStamp


class RunResultsResponse(BaseModel):
    """One run's 15 records, in R001..R015 order, exactly as the CLI emits them.

    ``explanations`` carries the provenance of each record's ``explanation``
    text beside the records — one entry per record, same order, same rule ids.
    It is deliberately *not* inside a record: the frozen result contract is
    exactly 15 keys, and the scorer rejects a sixteenth.

    Required rather than defaulted: a reader of this response always learns how
    the text they are about to read was produced. A run persisted without
    provenance (a direct store call, not the submission surface) answers with an
    empty list, which is the honest answer — not a marker invented from nothing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: RuleRun
    results: list[ResultRecord]
    explanations: list[ExplanationProvenance]


class RunClaimResponse(BaseModel):
    """The immutable input envelope for one run, used to prepare a correction.

    ClaimGuard's current dataset is synthetic. Exposing the stored run input here
    lets the reviewer edit a copy and submit a new version without mutating the
    audited original.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    claim_id: str
    version: int = Field(ge=1)
    claim: dict[str, Any]


class DecisionResponse(BaseModel):
    """A recorded decision, the finding's new review state and its audit stamp."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: StoredDecision
    review: ReviewState
    audit: AuditStamp


class DecisionHistoryEntry(BaseModel):
    """One decision in a run's history, with the review state it produced."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: StoredDecision
    review: ReviewState


class DecisionHistory(BaseModel):
    """Every decision recorded against one run, oldest first.

    No audit stamp per entry: several decisions can share a ``(rule_id, action)``
    pair (ask, then ask again), and the ledger's hash is not a stable identifier
    per decision row — the run's own stamp is the chain anchor, read from
    ``GET /v1/runs/{run_id}``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    entries: list[DecisionHistoryEntry]


class HealthResponse(BaseModel):
    """Honest readiness: which schema the store sees and which rules it loaded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    database: str
    schema_revision: str | None = None
    rules_dir: str | None = None
    rules_ready: bool
    engine_rule_version: str


def utc_now() -> datetime:
    """The current UTC time (used by tests and by nothing else)."""
    return datetime.now(UTC)


def summarize_statuses(records: Sequence[ResultRecord]) -> dict[str, int]:
    """Count records per pack status, with every status present (stable keys)."""
    counts = {status.value: 0 for status in Status}
    for record in records:
        counts[record.status.value] += 1
    return counts
