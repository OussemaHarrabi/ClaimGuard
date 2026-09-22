"""Explanation verification: the pack's contract plus the guards it asks for.

The pack ships ``validate_explanation`` in ``src/llm_adapter.py`` (4 exact keys,
citations drawn from the supplied evidence, the finding's rule id, the finding's
human-review boundary) and then says, in the same document, that it is not
enough (``docs/05_Architecture_and_AI.md``):

*   "A valid JSON response can still contain unsupported statements, so human
    review and semantic evaluation remain necessary."
*   "validate the output and verify that all citations refer to supplied inputs"
*   the prompt's own prohibitions: "Do not approve payment, infer clinical
    necessity, accuse anyone of fraud, invent coverage or create missing
    identifiers"; "Schema-valid output still needs evaluation for factual
    grounding."

This module implements the pack's checks **plus four guards the pack's own text
requires**:

1.  every citation must resolve in the ORIGINAL envelope (a citation to a real
    pointer of the wrong claim, or to a value that was rewritten, is not
    evidence);
2.  an explanation asserting approval, denial, payment or a clinical judgement
    is rejected — this is a *language* layer and it may not adjudicate;
3.  an empty explanation, or one that merely repeats the rule text, is rejected
    (it adds nothing a reviewer can act on);
4.  the finding's ``requires_human_review`` boundary is copied, never changed
    (the pack compares it by identity).

A rejected explanation is never shown as model text: the caller marks it and
uses the deterministic text instead. Rejection is always a *list of reasons*,
because the reviewer-facing report has to say why.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final, cast

from claimguard.edu.evidence import EvidenceError, resolve, values_match
from claimguard.edu.explain.fallback import evidence_pairs, evidence_paths

#: The pack's explanation output contract (``src/llm_adapter.py``).
EXPLANATION_KEYS: Final = (
    "explanation",
    "cited_evidence_paths",
    "cited_rule_ids",
    "needs_human_review",
)

#: Categories of language this layer may never produce, with the pattern that
#: detects them. Patterns are deliberately narrowed to *assertions*: quoting an
#: evidence value such as ``/authorizations/0/status = "denied"`` is data and
#: must stay acceptable, while "the claim is denied" is a decision.
PROHIBITED_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "adjudication_outcome",
        re.compile(
            r"\b(?:claim|payment|reimbursement|invoice)\b[^.!?]{0,40}"
            r"\b(?:is|are|was|were|will be|should be|must be|has been|have been|can be)\b"
            r"[^.!?]{0,20}\b(?:approved|denied|paid|rejected|accepted|covered|reimbursed)\b",
            re.IGNORECASE,
        ),
    ),
    ("approved_for_payment", re.compile(r"\bapproved for payment\b", re.IGNORECASE)),
    (
        "payer_decision",
        re.compile(
            r"\b(?:payer|insurer|plan|member)\b[^.!?]{0,30}"
            r"\b(?:approves?|approved|denies|denied|pays|paid|accepts?|accepted"
            r"|rejects?|rejected)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "clinical_judgement",
        re.compile(
            r"\bmedically necessary\b"
            r"|\bclinically (?:indicated|necessary|appropriate|justified)\b"
            r"|\bthe patient (?:needs|requires)\b"
            r"|\bdiagnosis (?:confirms|indicates|proves)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "payment_guarantee",
        re.compile(
            r"\bguarantee(?:s|d)?\b[^.!?]{0,30}"
            r"\b(?:payment|reimbursement|coverage|approval|acceptance)\b",
            re.IGNORECASE,
        ),
    ),
    ("fraud_accusation", re.compile(r"\b(?:fraud|fraudulent|upcoding)\b", re.IGNORECASE)),
)

#: Fields of the manifest rule that the echo guard treats as "the rule text".
_RULE_TEXT_FIELDS: Final = ("title", "logic", "corrective_action", "summary", "source")


class ExplanationRejectionError(ValueError):
    """A candidate explanation violates the contract; :attr:`reasons` says how."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons: tuple[str, ...] = tuple(reasons)
        super().__init__("; ".join(self.reasons))


def normalise(text: str) -> str:
    """Casefold, collapse whitespace and drop trailing punctuation."""
    return " ".join(text.split()).casefold().strip(" .!?;:")


def rule_text(rule: Mapping[str, Any]) -> str:
    """The concatenated manifest text of ``rule`` (the echo guard's corpus)."""
    parts = [
        value
        for field in _RULE_TEXT_FIELDS
        if isinstance((value := rule.get(field)), str) and value.strip()
    ]
    return normalise(" ".join(parts))


def prohibited_assertions(text: str) -> tuple[str, ...]:
    """Categories of prohibited assertion found in ``text`` (empty means clean)."""
    return tuple(name for name, pattern in PROHIBITED_PATTERNS if pattern.search(text))


def _string_list(value: Any) -> list[str] | None:
    """``value`` as a list of strings, or ``None`` when it is not one."""
    if not isinstance(value, list):
        return None
    items = cast("list[Any]", value)
    if any(not isinstance(item, str) for item in items):
        return None
    return cast("list[str]", items)


def _supplied_paths(finding: Mapping[str, Any]) -> list[str]:
    """Every evidence path the finding supplied (these are the only allowed ones)."""
    return evidence_paths(finding)


def _stored_values(finding: Mapping[str, Any]) -> dict[str, Any]:
    """Path → value as stored in the finding's own evidence list."""
    values: dict[str, Any] = {}
    for path, value in evidence_pairs(finding):
        values.setdefault(path, value)
    return values


def _citation_reasons(
    cited: Sequence[str], finding: Mapping[str, Any], envelope: Mapping[str, Any] | None
) -> list[str]:
    """Reasons why the cited paths are not genuine citations of the original claim."""
    reasons: list[str] = []
    allowed = set(_supplied_paths(finding))
    stored = _stored_values(finding)
    if envelope is not None:
        envelope_claim = envelope.get("claim_id")
        finding_claim = finding.get("claim_id")
        if isinstance(envelope_claim, str) and envelope_claim != finding_claim:
            reasons.append(
                f"envelope belongs to {envelope_claim!r}, not to the finding's claim "
                f"{finding_claim!r}"
            )
    for path in cited:
        if path not in allowed:
            reasons.append(f"citation {path!r} was not supplied with the finding")
            continue
        if envelope is None:
            continue
        try:
            observed = resolve(envelope, path)
        except EvidenceError as exc:
            reasons.append(f"citation {path!r} does not resolve in the original envelope: {exc}")
            continue
        if path in stored and not values_match(observed, stored[path]):
            reasons.append(
                f"citation {path!r} resolves to {observed!r} in the envelope, "
                f"not to the stored value {stored[path]!r}"
            )
    return reasons


def validate_explanation(
    output: Any,
    finding: Mapping[str, Any],
    *,
    envelope: Mapping[str, Any] | None = None,
    rule: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a candidate explanation; return a normalised 4-key copy.

    Raises :class:`ExplanationRejectionError` (all reasons, not just the first) on any
    breach. ``envelope`` is the ORIGINAL claim: supplying it enables citation
    resolution. ``rule`` is the manifest excerpt: supplying it enables the
    echo guard.
    """
    reasons: list[str] = []
    if not isinstance(output, Mapping):
        raise ExplanationRejectionError(["explanation output must be a JSON object"])
    candidate: dict[str, Any] = dict(cast("Mapping[str, Any]", output))
    missing = sorted(set(EXPLANATION_KEYS) - set(candidate))
    extra = sorted(set(candidate) - set(EXPLANATION_KEYS))
    if missing or extra:
        reasons.append(
            f"keys must be exactly {list(EXPLANATION_KEYS)} (missing={missing} extra={extra})"
        )

    text = candidate.get("explanation")
    if not isinstance(text, str) or not text.strip():
        reasons.append("explanation must be a non-empty string")
        text = ""
    else:
        found = prohibited_assertions(text)
        if found:
            reasons.append(
                "explanation asserts an adjudication or clinical conclusion "
                f"({', '.join(found)}); this layer explains, it never decides"
            )
        if rule is not None:
            corpus = rule_text(rule)
            normalised = normalise(text)
            if corpus and normalised and normalised in corpus:
                reasons.append("explanation merely repeats the rule text")

    cited = _string_list(candidate.get("cited_evidence_paths"))
    if not cited:
        reasons.append("cited_evidence_paths must be a non-empty list of strings")
    else:
        reasons.extend(_citation_reasons(cited, finding, envelope))

    cited_rules = _string_list(candidate.get("cited_rule_ids"))
    expected_rule = finding.get("rule_id")
    if cited_rules is None:
        reasons.append("cited_rule_ids must be a list of strings")
    elif cited_rules != [expected_rule]:
        reasons.append(f"cited_rule_ids must be exactly [{expected_rule!r}], got {cited_rules!r}")

    review = candidate.get("needs_human_review")
    if not isinstance(review, bool):
        reasons.append("needs_human_review must be a boolean")
    elif review is not finding.get("requires_human_review"):
        reasons.append("needs_human_review must equal the finding's requires_human_review")

    if reasons:
        raise ExplanationRejectionError(reasons)
    return {key: candidate[key] for key in EXPLANATION_KEYS}
