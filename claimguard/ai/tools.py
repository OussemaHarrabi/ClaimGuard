"""The assistant's context tools: reads of a stored run, pure and total.

WHAT THESE ARE, AND WHY THEY ARE NOT LANGCHAIN TOOLS
----------------------------------------------------
They are the "gather" vocabulary of the graph. Each one reads something the rule
engine already produced — one 15-key result record, the ORIGINAL claim envelope,
the catalogue entry for its rule, the claim's policy values — and returns a
plain, JSON-able view. They perform no I/O, hold no state, open no socket, call
no model, and never raise on a malformed input: a value that is absent is
reported as absent (the :data:`MISSING` sentinel), never invented and never a
crash. That totality is the point. `gather` runs before the only model call, and
a context tool that could fail would be a new way for the assistant to fail
before the reviewer ever gets an answer.

They are deliberately *not* exposed as a model-callable tool belt: this assistant
answers questions about one finding it was already given, and a model that could
decide which claim to fetch would be a model that could decide what to explain.
The graph calls these; the model never does.

WHAT MAY LEAVE THIS MODULE
--------------------------
Only the finding's own fields, evidence pointers re-resolved against the
original claim, the rule's catalogue text, and the policy values the BUILT-IN
rule reads (mapped in :data:`RULE_POLICY_FIELDS`). Notes and attachment text are
claim *data*; they never enter the context, so a model cannot explain something
the engine did not find.

Totality includes the record's evidence list. `answer_question` refuses a record
whose evidence is malformed before the graph runs (that is what
`AssistantInputError` is for), but these readers still report such a record as
"no evidence" instead of raising: a context tool that could raise would be a
second way for the assistant to fail in front of a reviewer, and it would fail
*after* the one place that already decided the record was unusable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final, cast

from claimguard.ai.schemas import ASSISTANT_KEYS
from claimguard.edu.evidence import EvidenceError, resolve
from claimguard.edu.explain.fallback import (
    FallbackError,
    evidence_pairs,
    evidence_paths,
    render_value,
)


class MissingValue:
    """A pointer that does not resolve in the envelope it was asked about.

    A sentinel rather than ``None``: a JSON pointer may legitimately resolve to
    ``null``, and "the claim says nothing here" must stay distinguishable from
    "the claim says the value is null". Falsy, so ``if not value`` reads as the
    question a caller actually means, and a single class means ``isinstance``
    works where a bare ``object()`` would need identity comparisons.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


#: The one sentinel instance. Compared with :func:`is_missing`.
MISSING: Final = MissingValue()

#: Result-record fields worth showing a model (the engine's own values, nothing derived).
FINDING_FIELDS: Final[tuple[str, ...]] = (
    "claim_id",
    "rule_id",
    "rule_version",
    "status",
    "severity",
    "affected_line_ids",
    "explanation",
    "corrective_action",
    "requires_human_review",
    "confidence",
    "confidence_kind",
    "method",
    "review_status",
    "rule_source",
)

#: Catalogue fields that make a rule's own text, and the ones describing it.
RULE_FIELDS: Final[tuple[str, ...]] = (
    "rule_id",
    "title",
    "severity",
    "version",
    "source",
    "corrective_action",
)

#: Longest rule `logic` excerpt forwarded. The rule's logic IS what the reviewer
#: is asking about, so it is included, but a 2 kB condition is not a prompt.
RULE_LOGIC_CHARS: Final = 900

#: Policy identity, always included so the model knows which profile it read.
POLICY_IDENTITY_FIELDS: Final[tuple[str, ...]] = ("policy_id", "version", "payer_id", "currency")

#: Which policy values each built-in rule actually reads (docs/04_Rulebook.md).
#: A rule absent from this map is given the identity only: sending every policy
#: key to every rule would invite a model to reason about limits the rule never
#: applied, which is exactly the invented-coverage failure the pack forbids.
RULE_POLICY_FIELDS: Final[Mapping[str, tuple[str, ...]]] = {
    "R005": ("allowed_providers",),
    "R008": ("auth_required_services",),
    "R009": ("auth_required_services",),
    "R010": ("required_documents",),
    "R013": ("max_unit_price", "max_quantity_per_line"),
    "R014": ("submission_window_days",),
    "R015": ("currency",),
}

#: Policy fields keyed by service code: narrowed to the claim's own services, so
#: the prompt shows the limits that bear on this claim rather than the catalogue.
SERVICE_KEYED_POLICY_FIELDS: Final[tuple[str, ...]] = (
    "required_documents",
    "max_unit_price",
    "max_quantity_per_line",
)

#: How many evidence values reach the prompt before the rest are summarised.
MAX_CONTEXT_EVIDENCE: Final = 12


def is_missing(value: Any) -> bool:
    """True when ``value`` is the :data:`MISSING` sentinel."""
    return isinstance(value, MissingValue)


def claim_value(envelope: Mapping[str, Any], pointer: str) -> Any:
    """Resolve one RFC-6901 ``pointer`` against the ORIGINAL claim envelope.

    Returns the exact object found, or :data:`MISSING` when the pointer is
    malformed, does not resolve, or walks into a scalar. Returning a sentinel
    instead of raising is what lets `gather` report "the claim does not carry
    this value" — which is itself an answer a reviewer may need.
    """
    if not pointer:
        return MISSING
    try:
        return resolve(envelope, pointer)
    except EvidenceError:
        return MISSING
    except (TypeError, KeyError, IndexError):
        # A non-JSON document (a list root, a scalar field) is not an error here:
        # it is a value this claim does not carry at that pointer.
        return MISSING


def claim_service_codes(envelope: Mapping[str, Any]) -> list[str]:
    """The distinct service codes of the claim's lines, in order (missing ones skipped)."""
    lines = envelope.get("lines")
    if not isinstance(lines, list):
        return []
    codes: list[str] = []
    for line in cast("list[Any]", lines):
        if not isinstance(line, Mapping):
            continue
        code = cast("Mapping[str, Any]", line).get("service_code")
        if isinstance(code, str) and code.strip() and code not in codes:
            codes.append(code)
    return codes


def finding_context(finding: Mapping[str, Any]) -> dict[str, Any]:
    """The finding as the model may see it: the engine's own fields plus its evidence.

    Evidence values are rendered (JSON-encoded, elided when long) and never
    re-typed: they are the values the record stored, which the verifier will later
    re-check against the envelope.
    """
    context: dict[str, Any] = {
        field: finding[field] for field in FINDING_FIELDS if field in finding
    }
    context["requires_human_review"] = finding.get("requires_human_review") is True
    pairs = _safe_evidence_pairs(finding)
    shown = pairs[:MAX_CONTEXT_EVIDENCE]
    context["evidence"] = [{"path": path, "value": render_value(value)} for path, value in shown]
    context["evidence_count"] = len(pairs)
    if len(pairs) > len(shown):
        context["evidence_omitted"] = [path for path, _ in pairs[len(shown) :]]
    return context


def rule_context(rule: Mapping[str, Any]) -> dict[str, Any]:
    """The catalogue entry for the finding's rule, with its own text preserved."""
    context: dict[str, Any] = {field: rule[field] for field in RULE_FIELDS if field in rule}
    logic = rule.get("logic")
    if isinstance(logic, str) and logic.strip():
        collapsed = " ".join(logic.split())
        context["logic"] = (
            collapsed
            if len(collapsed) <= RULE_LOGIC_CHARS
            else collapsed[: RULE_LOGIC_CHARS - 3] + "..."
        )
    return context


def policy_context(
    policy: Mapping[str, Any],
    rule_id: str,
    service_codes: Sequence[str],
) -> dict[str, Any]:
    """The policy values ``rule_id`` reads, narrowed to the claim's own services.

    An absent policy (an unknown ``policy_id`` is "no matching policy was
    supplied", never a default) yields an empty mapping — the model is told
    nothing rather than given the values of a profile this claim does not have.
    """
    if not policy:
        return {}
    context: dict[str, Any] = {
        field: policy[field] for field in POLICY_IDENTITY_FIELDS if field in policy
    }
    requested = RULE_POLICY_FIELDS.get(rule_id, ())
    for field in requested:
        value = policy.get(field)
        if field in SERVICE_KEYED_POLICY_FIELDS and isinstance(value, Mapping):
            catalogue = cast("Mapping[str, Any]", value)
            scoped = {
                code: catalogue[code] for code in _distinct(service_codes) if code in catalogue
            }
            if scoped:
                context[field] = scoped
        elif value is not None:
            context[field] = value
    if any(field in requested for field in SERVICE_KEYED_POLICY_FIELDS):
        context["service_codes"] = _distinct(service_codes)
    return context


def envelope_values(envelope: Mapping[str, Any], finding: Mapping[str, Any]) -> dict[str, str]:
    """Each of the finding's pointers re-resolved in the ORIGINAL claim, rendered.

    This is the citation the reviewer can check: the same pointer the verifier
    will resolve, printed as the envelope holds it today. A pointer that no
    longer resolves is reported as ``MISSING`` rather than dropped, because that
    disagreement is itself what the reviewer needs to see.
    """
    values: dict[str, str] = {}
    for path in _safe_evidence_paths(finding):
        value = claim_value(envelope, path)
        values[path] = "MISSING" if is_missing(value) else render_value(value)
    return values


def answer_contract(finding: Mapping[str, Any]) -> dict[str, Any]:
    """The machine-checkable part of the contract, restated next to the data.

    The prompt already says "copy the pointers, keep the rule id, do not
    downgrade the review flag"; putting the exact values one line away from the
    finding is what makes a small model's answer pass the verifier instead of
    being refused for a reason the reviewer would never see.
    """
    return {
        "keys": list(ASSISTANT_KEYS),
        "cited_rule_ids_must_equal": [finding.get("rule_id")],
        "needs_human_review_must_equal": finding.get("requires_human_review") is True,
        "allowed_cited_evidence_paths": _safe_evidence_paths(finding),
    }


def _safe_evidence_pairs(finding: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """The record's ``(path, value)`` pairs, or none when its evidence is malformed."""
    try:
        return evidence_pairs(finding)
    except FallbackError:
        return []


def _safe_evidence_paths(finding: Mapping[str, Any]) -> list[str]:
    """The record's evidence pointers, or none when its evidence is malformed."""
    try:
        return evidence_paths(finding)
    except FallbackError:
        return []


def _distinct(values: Sequence[str]) -> list[str]:
    """Non-blank strings, de-duplicated, order preserved."""
    seen: list[str] = []
    for value in values:
        if value.strip() and value not in seen:
            seen.append(value)
    return seen
