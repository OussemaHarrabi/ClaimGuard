"""Deterministic explanation path — the always-available, non-model fallback.

Bounded-AI contract (pack ``docs/05_Architecture_and_AI.md``, "AI exercise" and
"Agent behaviour to demonstrate"; ``docs/07_Evaluation_and_Acceptance.md``,
"AI evaluation"): a model may draft *language*, it never decides an outcome.
When no model is configured, or the model is slow, malformed or rejected by the
verifier, the reviewer must still receive a complete, evidence-linked
explanation of what the deterministic engine found — and the text must be
attributable.

Attribution is structural, not decorative: every text produced here starts with
:data:`DETERMINISTIC_PREFIX`, and the model path prefixes validated model text
with :data:`MODEL_PREFIX` (see :mod:`claimguard.edu.explain.provider`). A
reviewer reading an enriched result therefore always knows which text a model
wrote, without extra tooling.

The text is built only from the validated finding (status, severity, the
engine's own explanation, corrective action) and the manifest rule excerpt
(title). It never quotes untrusted free text such as ``notes`` or attachment
``text``: those are claim *data*, and an explanation that echoed them would be
indistinguishable from one that followed them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final, cast

# ---------------------------------------------------------------------------
# Provenance markers
# ---------------------------------------------------------------------------

#: Prefix on every text this module produces (deterministic provenance).
DETERMINISTIC_PREFIX: Final = "[deterministic] "
#: Prefix applied by the model path to validated model text.
MODEL_PREFIX: Final = "[model] "

SOURCE_DETERMINISTIC: Final = "deterministic"
SOURCE_MODEL: Final = "model"

#: How many evidence pointers are spelled out in the text. All of them are
#: still cited in ``cited_evidence_paths``; the finding stays available too.
MAX_RENDERED_EVIDENCE: Final = 6
#: Longest value rendered verbatim before it is elided.
MAX_VALUE_CHARS: Final = 80

#: Status → clause used in the lead sentence.
_STATUS_LEAD: Final[Mapping[str, str]] = {
    "FAIL": "reports FAIL",
    "UNABLE_TO_ASSESS": "could not be assessed",
    "PASS": "reports PASS",
    "NOT_APPLICABLE": "does not apply",
    "NOT_IMPLEMENTED": "is NOT_IMPLEMENTED",
}

#: Status → reviewer step when the manifest supplies no corrective action.
_STATUS_STEP: Final[Mapping[str, str]] = {
    "PASS": "No reviewer action is requested by this rule; a pass is not payer acceptance.",
    "NOT_APPLICABLE": "No reviewer action is requested: this rule's scope excludes the claim.",
    "NOT_IMPLEMENTED": (
        "This check is not implemented and must never be read as a pass; it is an open gap."
    ),
}


class FallbackError(ValueError):
    """The finding is not a usable result record, so no text can be built."""


def mark_deterministic(text: str) -> str:
    """Return ``text`` carrying the deterministic marker exactly once."""
    stripped = text.strip()
    if stripped.startswith(DETERMINISTIC_PREFIX):
        return stripped
    return f"{DETERMINISTIC_PREFIX}{stripped}"


def mark_model(text: str) -> str:
    """Return ``text`` carrying the model marker exactly once."""
    stripped = text.strip()
    if stripped.startswith(MODEL_PREFIX):
        return stripped
    return f"{MODEL_PREFIX}{stripped}"


def render_value(value: Any, *, max_chars: int = MAX_VALUE_CHARS) -> str:
    """Render one evidence value compactly and unambiguously.

    Values are JSON-encoded (so ``null`` and ``"null"`` stay distinguishable)
    and elided rather than truncated mid-token when very long.
    """
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):  # pragma: no cover - engine evidence is JSON
        rendered = repr(value)
    if len(rendered) > max_chars:
        return rendered[: max_chars - 3] + "..."
    return rendered


def _required_text(mapping: Mapping[str, Any], key: str) -> str:
    """Read a non-empty string field of a result record or raise."""
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FallbackError(f"Finding is missing the required string field {key!r}")
    return value.strip()


def _sentence(text: str) -> str:
    """Return ``text`` with collapsed whitespace and exactly one trailing period."""
    collapsed = " ".join(text.split())
    if not collapsed:
        return collapsed
    return collapsed if collapsed.endswith((".", "!", "?")) else f"{collapsed}."


def _entries(finding: Mapping[str, Any]) -> list[Any]:
    """The finding's raw evidence list, or a :class:`FallbackError`."""
    entries = finding.get("evidence")
    if not isinstance(entries, list):
        raise FallbackError("Finding is missing its evidence list")
    return cast("list[Any]", entries)


def _pointer(entry: Any) -> str:
    """The evidence pointer of one entry, or a :class:`FallbackError`."""
    if not isinstance(entry, Mapping):
        raise FallbackError("Every evidence entry must be an object")
    pointer = cast("Mapping[str, Any]", entry).get("path")
    if not isinstance(pointer, str):
        raise FallbackError("Every evidence entry needs a string 'path'")
    return pointer


def evidence_paths(finding: Mapping[str, Any]) -> list[str]:
    """The supplied evidence pointers, de-duplicated, in the finding's order."""
    paths: list[str] = []
    for entry in _entries(finding):
        pointer = _pointer(entry)
        if pointer not in paths:
            paths.append(pointer)
    return paths


def evidence_pairs(finding: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """Supplied evidence as ``(path, value)`` pairs, de-duplicated by path."""
    pairs: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for entry in _entries(finding):
        pointer = _pointer(entry)
        if pointer in seen:
            continue
        seen.add(pointer)
        value = (
            cast("Mapping[str, Any]", entry).get("value") if isinstance(entry, Mapping) else None
        )
        pairs.append((pointer, value))
    return pairs


def build_text(finding: Mapping[str, Any], rule: Mapping[str, Any]) -> str:
    """Build the deterministic explanation text for one result record.

    Raises :class:`FallbackError` when the finding is not a usable result record
    (the caller then has nothing trustworthy to explain).
    """
    rule_id = _required_text(finding, "rule_id")
    claim_id = _required_text(finding, "claim_id")
    status = _required_text(finding, "status")
    severity = _required_text(finding, "severity")
    detail = _sentence(_required_text(finding, "explanation"))
    pairs = evidence_pairs(finding)
    lead = _STATUS_LEAD.get(status, f"reports {status}")
    title = rule.get("title")
    titled = f' "{title}"' if isinstance(title, str) and title.strip() else ""

    if pairs:
        shown = pairs[:MAX_RENDERED_EVIDENCE]
        rendered = ", ".join(f"{path} = {render_value(value)}" for path, value in shown)
        more = len(pairs) - len(shown)
        tail = f" (+{more} more cited in the finding)" if more else ""
        evidence = f"Evidence ({len(pairs)} pointer(s) into the original claim): {rendered}{tail}."
    else:
        evidence = "No evidence pointer is attached to this result."

    action = finding.get("corrective_action")
    if not isinstance(action, str) or not action.strip():
        action = rule.get("corrective_action")
    if not isinstance(action, str) or not action.strip():
        step = _STATUS_STEP.get(status, "")
    else:
        step = f"Reviewer step: {_sentence(action)}"
    review = (
        "Human review is required."
        if finding.get("requires_human_review") is True
        else "This result does not require human review."
    )
    parts = [
        f"Rule {rule_id}{titled} {lead} (severity {severity}) for claim {claim_id}.",
        f"Detected: {detail}",
        evidence,
        step,
        review,
        "The rule engine's status is unchanged by this text.",
    ]
    return mark_deterministic(" ".join(part for part in parts if part))


def build_explanation(finding: Mapping[str, Any], rule: Mapping[str, Any]) -> dict[str, Any]:
    """Build the deterministic explanation output (the pack's 4-key contract).

    ``cited_evidence_paths`` is the finding's own evidence set (so the citation
    contract holds by construction), ``cited_rule_ids`` is exactly the finding's
    rule id, and ``needs_human_review`` is copied from ``requires_human_review``
    — never re-derived.
    """
    rule_id = _required_text(finding, "rule_id")
    return {
        "explanation": build_text(finding, rule),
        "cited_evidence_paths": evidence_paths(finding),
        "cited_rule_ids": [rule_id],
        "needs_human_review": finding.get("requires_human_review") is True,
    }
