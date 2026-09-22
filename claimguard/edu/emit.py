"""Result emission: build, validate and serialize the frozen 15-key record.

Contract sources: ``schemas/result.schema.json`` and the pack scorer
``src/evaluate.py::index`` — which requires

*   exactly the 15 keys (no extra, no missing),
*   ``rule_version == "1.0.0"`` and ``rule_source == fictional-rulebook/<RID>@1.0.0``,
*   a non-empty evidence list for every status except ``NOT_IMPLEMENTED``,
*   ``requires_human_review`` and a non-empty ``corrective_action`` for FAIL and
    UNABLE_TO_ASSESS,
*   ``confidence`` null whenever ``confidence_kind == "not_probabilistic"``,
*   evidence pointers that re-resolve to the exact stored value.

Severity, version, source and corrective action are copied from the pack rule
manifest (``rules/rules.json``), never invented here.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast

from pydantic import ValidationError

from claimguard.edu.envelope import (
    RESULT_KEYS,
    Claim,
    ConfidenceKind,
    ContractError,
    Result,
    ResultRecord,
    Status,
)
from claimguard.edu.evidence import EvidenceError, build_evidence, verify_evidence
from claimguard.edu.policy import RuleMeta

CORRECTIVE_STATUSES = (Status.FAIL, Status.UNABLE_TO_ASSESS)

#: Explanation used when a rule's evidence satisfies it (reference wording).
SATISFIED = "The supplied evidence satisfies this fictional rule."
#: Explanation used when a rule's scope does not cover the claim.
NOT_APPLICABLE = "Rule does not apply to the supplied claim."


def format_findings(messages: Iterable[str]) -> str:
    """Join distinct finding phrases deterministically (sorted, '; '-separated).

    Multiple findings are intentional and are not mutually exclusive
    (docs/04_Rulebook.md:10), so a rule aggregates every phrase it proved.
    """
    return "; ".join(sorted(set(messages)))


def make_result(
    claim: Claim,
    meta: RuleMeta,
    status: Status,
    explanation: str,
    pointers: Iterable[str],
    line_ids: Sequence[str] = (),
) -> Result:
    """Build one result record for ``claim`` and the manifest ``meta``.

    ``pointers`` are JSON pointers into the ORIGINAL envelope; their values are
    resolved there and stored verbatim, and ``line_ids`` carry the stable
    ``line_id`` identifiers (never array offsets).
    """
    resolved = Status(status)
    flagged = resolved in CORRECTIVE_STATUSES
    return {
        "claim_id": claim["claim_id"],
        "rule_id": meta.rule_id,
        "rule_version": meta.version,
        "status": resolved.value,
        "severity": meta.severity.value,
        "affected_line_ids": list(dict.fromkeys(line_ids)),
        "evidence": build_evidence(claim, pointers),
        "rule_source": meta.source,
        "explanation": explanation,
        "corrective_action": meta.corrective_action if flagged else "",
        "confidence": None,
        "confidence_kind": ConfidenceKind.NOT_PROBABILISTIC.value,
        "requires_human_review": flagged,
        "method": "deterministic",
        "review_status": "unreviewed",
    }


def validate_record(record: Mapping[str, Any], claim: Claim | None = None) -> ResultRecord:
    """Validate one record against the frozen contract; raise :class:`ContractError`.

    With ``claim`` supplied, the record is additionally checked against that
    original envelope: the claim id must match, every ``affected_line_ids`` entry
    must exist, and every evidence pointer must re-resolve to its stored value.
    """
    if set(record) != set(RESULT_KEYS):
        missing = sorted(set(RESULT_KEYS) - set(record))
        extra = sorted(set(record) - set(RESULT_KEYS))
        raise ContractError(
            f"Result keys must match the contract exactly; missing={missing} extra={extra}"
        )
    try:
        validated = ResultRecord.model_validate(dict(record))
    except ValidationError as exc:
        raise ContractError(f"Invalid result record: {exc}") from exc
    if claim is not None:
        _check_against_claim(record, validated, claim)
    return validated


def _check_against_claim(record: Mapping[str, Any], validated: ResultRecord, claim: Claim) -> None:
    """Cross-check one validated record against the envelope it claims to describe."""
    if validated.claim_id != claim["claim_id"]:
        raise ContractError(f"Result claim_id {validated.claim_id!r} does not match the claim")
    known_ids = {line["line_id"] for line in claim["lines"]}
    unknown = sorted(set(validated.affected_line_ids) - known_ids)
    if unknown:
        raise ContractError(f"Unknown affected line ids: {unknown}")
    entries = record["evidence"]
    if not isinstance(entries, list):  # pragma: no cover - model validation guarantees a list
        raise ContractError("Evidence must be a list")
    try:
        verify_evidence(claim, cast("list[Mapping[str, Any]]", entries))
    except EvidenceError as exc:
        raise ContractError(str(exc)) from exc


def serialize(record: Mapping[str, Any], claim: Claim | None = None) -> str:
    """Validate then serialize one record as a single JSON object line."""
    validate_record(record, claim)
    ordered = {key: record[key] for key in RESULT_KEYS}
    try:
        return json.dumps(ordered, ensure_ascii=False)
    except TypeError as exc:
        raise ContractError(f"Result is not JSON-serializable: {exc}") from exc
