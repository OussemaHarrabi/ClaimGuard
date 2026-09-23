"""The three questions we ask, and the state we ask them about.

**Why exactly three.** The deterministic engine already decides the status; this
layer is a second opinion, so it must ask only what a second opinion can add and
only about things the graded contract does not already contain:

1.  ``grounded`` (``noul``) — *is every statement in the explanation supported
    by the cited evidence?* The engine can prove that its pointers resolve; it
    cannot prove that the prose it built from them says no more than they show.
    This is the one question that can catch an over-claiming explanation.
2.  ``status_agreement`` (``choice``) — *a second opinion on the rule's own
    status.* Agreement is informative (it is a signal about the rule, not a new
    status); disagreement is a routing hint for a human. It is deliberately a
    separate record from the status it comments on.
3.  ``attention`` (``score``) — *how much human attention does this finding
    deserve?* Severity is fixed per rule by the manifest, so a queue full of
    ``high`` findings still needs a triage order. This is a ranking, not a
    severity.

**What we send.** :func:`build_state` sends the validated record, its evidence
pointers (path + value, extracted from the record's own ``evidence`` array) and a
bounded excerpt of the rule manifest entry. Nothing else: no claim envelope, no
patient identifiers beyond what the record already carries, no credentials, no
notes, no attachment text. The builder is pure — it takes a mapping and returns
data, so it can be tested without a provider, a network or a key.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, cast

from claimguard.edu.envelope import RESULT_KEYS
from claimguard.edu.judge.models import (
    AgreementChoice,
    AttentionLevel,
    ChoiceQuestion,
    NoulQuestion,
    Question,
    ScoreQuestion,
    SystemOneRequest,
)
from claimguard.edu.policy import RuleMeta

#: Answer keys, echoed back by the API exactly as written here.
QUESTION_GROUNDED: Final = "grounded"
QUESTION_STATUS_AGREEMENT: Final = "status_agreement"
QUESTION_ATTENTION: Final = "attention"

#: The question set, in the order it is built and answered.
QUESTION_NAMES: Final = (QUESTION_GROUNDED, QUESTION_STATUS_AGREEMENT, QUESTION_ATTENTION)

#: Rule-manifest fields forwarded as the excerpt (the manifest is the authority).
RULE_EXCERPT_FIELDS: Final = (
    "rule_id",
    "title",
    "severity",
    "logic",
    "corrective_action",
    "version",
    "source",
)

#: Longest rule ``logic`` excerpt forwarded — enough to judge, not the whole rulebook.
RULE_EXCERPT_CHARS: Final = 600

#: What each ordered attention level means (position in the list *is* the score).
_ATTENTION_DESCRIPTIONS: Final[Mapping[AttentionLevel, str]] = {
    AttentionLevel.CAN_WAIT: (
        "the finding is informational for this claim; the normal review queue is enough"
    ),
    AttentionLevel.THIS_WEEK: ("a reviewer should look at this claim during the current week"),
    AttentionLevel.TODAY: (
        "a reviewer should look at this claim today, before it is processed further"
    ),
}


class QuestionError(ValueError):
    """The supplied record cannot be turned into a contract-valid question set."""


def _finding(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the record's own fields, refusing anything that is not a graded record.

    Judging is only ever done on a validated 15-key record: a mapping with extra
    or missing keys is a caller error, not something to send to a model.
    """
    missing = [key for key in RESULT_KEYS if key not in record]
    if missing:
        raise QuestionError(f"record is missing contract keys: {', '.join(missing)}")
    unexpected = sorted(key for key in record if key not in RESULT_KEYS)
    if unexpected:
        raise QuestionError(f"record carries non-contract keys: {', '.join(unexpected)}")
    return {key: record[key] for key in RESULT_KEYS}


def rule_excerpt(rule: RuleMeta | Mapping[str, Any]) -> dict[str, Any]:
    """The bounded rule-manifest excerpt needed to judge one finding."""
    source = rule.model_dump(mode="json") if isinstance(rule, RuleMeta) else dict(rule)
    excerpt = {field: source[field] for field in RULE_EXCERPT_FIELDS if field in source}
    if not excerpt:
        raise QuestionError("rule manifest entry has none of the excerpt fields")
    logic = excerpt.get("logic")
    if isinstance(logic, str):
        excerpt["logic"] = logic[:RULE_EXCERPT_CHARS]
    return excerpt


def build_state(record: Mapping[str, Any], rule: RuleMeta | Mapping[str, Any]) -> dict[str, Any]:
    """The content the questions refer to: the record, its evidence, the rule excerpt."""
    finding = _finding(record)
    return {
        "finding": finding,
        "evidence": _evidence_pairs(finding["evidence"]),
        "rule_excerpt": rule_excerpt(rule),
    }


def _evidence_pairs(evidence: Any) -> list[dict[str, Any]]:
    """The record's evidence as ``{path, value}`` pairs, or a refusal."""
    if not isinstance(evidence, list):
        raise QuestionError("record evidence is not a list")
    pairs: list[dict[str, Any]] = []
    for raw in cast("list[Any]", evidence):
        if not isinstance(raw, dict):
            raise QuestionError("record evidence entry is not an object")
        entry = cast("dict[str, Any]", raw)
        pairs.append({"path": entry["path"], "value": entry["value"]})
    return pairs


def build_questions(record: Mapping[str, Any]) -> dict[str, Question]:
    """The three questions, built from the record's own fields (never invented ones)."""
    finding = _finding(record)
    claim_id = finding["claim_id"]
    rule_id = finding["rule_id"]
    status = finding["status"]
    subject = f"Claim {claim_id}, rule {rule_id}, reported status {status}."
    return {
        QUESTION_GROUNDED: NoulQuestion(
            instructions=(
                f"{subject} Is every statement in the finding's explanation supported by the "
                "evidence cited in its evidence list, and by nothing else? Answer with the "
                "probability that it is fully supported."
            ),
            criteria={
                "true": ("every statement in the explanation is supported by the cited evidence"),
                "false": (
                    "at least one statement is unsupported by, contradicted by, or goes "
                    "beyond the cited evidence"
                ),
            },
        ),
        QUESTION_STATUS_AGREEMENT: ChoiceQuestion(
            instructions=(
                f"{subject} That status was produced by a deterministic rule, not by you. "
                "Reading the finding and its evidence, is that the status you would report? "
                "Choose the single closest option."
            ),
            criteria={
                AgreementChoice.AGREE.value: (
                    "the reported status is the correct status for the cited evidence"
                ),
                AgreementChoice.AGREE_BUT_LOW_CONFIDENCE.value: (
                    "the reported status is probably correct, but the cited evidence is thin, "
                    "ambiguous or incomplete"
                ),
                AgreementChoice.DISAGREE.value: (
                    "the reported status is wrong for the cited evidence"
                ),
            },
        ),
        QUESTION_ATTENTION: ScoreQuestion(
            instructions=(
                f"{subject} How much human attention does this finding deserve? Answer with "
                "the position of one level in the criteria list, counting from 0."
            ),
            criteria=[
                f"{level.value}: {_ATTENTION_DESCRIPTIONS[level]}" for level in AttentionLevel
            ],
        ),
    }


def build_envelope(
    model: str, record: Mapping[str, Any], rule: RuleMeta | Mapping[str, Any]
) -> SystemOneRequest:
    """The full request envelope for one record — validated before it can be sent."""
    return SystemOneRequest(
        model=model, state=build_state(record, rule), questions=build_questions(record)
    )


def build_body(
    model: str, record: Mapping[str, Any], rule: RuleMeta | Mapping[str, Any]
) -> dict[str, Any]:
    """The exact JSON body of one judge request (the payload reviewed against the contract)."""
    return build_envelope(model, record, rule).model_dump(mode="json")
