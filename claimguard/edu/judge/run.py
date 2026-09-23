"""Run the advisory judge over validated records, and derive the human-readable part.

The order of operations is the safety boundary made executable:

1.  the record must be a validated 15-key contract record (``build_state`` refuses
    anything else);
2.  its evidence must re-resolve against the claim envelope it came from, or the
    finding is never sent anywhere (``skipped``);
3.  the provider is asked — and *only* the provider decides whether that is a
    no-op (:class:`~claimguard.edu.judge.provider.NullJudge`) or a real call;
4.  every failure — disabled, timeout, HTTP error, malformed body, unexpected
    answer — becomes a typed, inert outcome on that one assessment. Nothing
    propagates, nothing is retried, and no record is touched.

The result is one :class:`~claimguard.edu.judge.models.JudgeAssessment` per input
record, in input order. The records themselves are never read into the
assessment and never written to.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from claimguard.edu.envelope import Result, load_jsonl
from claimguard.edu.evidence import EvidenceError, verify_evidence
from claimguard.edu.judge.models import (
    AdvisorySummary,
    AgreementChoice,
    AttentionLevel,
    ChoiceAnswer,
    JudgeAssessment,
    JudgeStatus,
    NoulAnswer,
    Question,
    ScoreAnswer,
    SystemOneResponse,
    Usage,
)
from claimguard.edu.judge.provider import (
    JudgeDisabledError,
    JudgeError,
    JudgeProvider,
    JudgeResponseError,
)
from claimguard.edu.judge.questions import (
    QUESTION_ATTENTION,
    QUESTION_GROUNDED,
    QUESTION_STATUS_AGREEMENT,
    build_questions,
    build_state,
)
from claimguard.edu.policy import RuleContext, RuleMeta

#: Wall-clock source for latency, injectable so tests are deterministic.
Clock = Callable[[], float]

#: Why an assessment is not ``assessed``.
REASON_ASSESSED: Final = "the model answered every question"
REASON_NO_RULE: Final = "the rule is not in the loaded manifest"
REASON_NO_CLAIM: Final = (
    "the record's claim was not supplied, so its evidence cannot be re-verified"
)
REASON_EVIDENCE: Final = "the record's evidence does not resolve against the supplied claim"


def load_rule_manifest(rules_dir: str | Path) -> dict[str, RuleMeta]:
    """Load the rule manifest the excerpt comes from (read-only, the pack's ``rules/``)."""
    return dict(RuleContext.from_rules_dir(rules_dir).rules)


def load_claim_envelopes(path: str | Path) -> dict[str, dict[str, Any]]:
    """Load claim envelopes keyed by ``claim_id`` (the document evidence resolves against)."""
    return {
        str(envelope["claim_id"]): envelope
        for envelope in load_jsonl(path)
        if isinstance(envelope.get("claim_id"), str)
    }


def assess_record(
    record: Result,
    *,
    rule: RuleMeta | Mapping[str, Any] | None,
    claim: Mapping[str, Any],
    provider: JudgeProvider,
    clock: Clock = time.perf_counter,
) -> JudgeAssessment:
    """Judge one validated record against one claim envelope; never raise for a judge fault."""
    claim_id = str(record["claim_id"])
    rule_id = str(record["rule_id"])
    if rule is None:
        return _skipped(claim_id, rule_id, provider, REASON_NO_RULE)
    try:
        verify_evidence(claim, record["evidence"])
    except EvidenceError as exc:
        return _skipped(claim_id, rule_id, provider, f"{REASON_EVIDENCE}: {exc}")

    state = build_state(record, rule)
    questions = build_questions(record)
    started = clock()
    try:
        response = provider.assess(state, questions)
    except JudgeDisabledError as exc:
        return _skipped(claim_id, rule_id, provider, str(exc))
    except JudgeError as exc:
        return _failed(claim_id, rule_id, provider, str(exc), questions=questions)
    except Exception as exc:  # noqa: BLE001 - the boundary: an unknown judge fault is inert
        return _failed(
            claim_id,
            rule_id,
            provider,
            f"unexpected judge failure: {type(exc).__name__}",
            questions=questions,
        )
    latency_ms = (clock() - started) * 1000.0
    return _assessed(claim_id, rule_id, provider, response, questions, latency_ms)


def assess_records(
    records: Sequence[Result],
    *,
    rules: Mapping[str, RuleMeta | Mapping[str, Any]],
    claims: Mapping[str, Mapping[str, Any]],
    provider: JudgeProvider,
    clock: Clock = time.perf_counter,
) -> list[JudgeAssessment]:
    """Judge many records, returning one assessment per record in input order."""
    assessments: list[JudgeAssessment] = []
    for record in records:
        claim_id = str(record["claim_id"])
        claim = claims.get(claim_id)
        if claim is None:
            assessments.append(
                _skipped(claim_id, str(record["rule_id"]), provider, REASON_NO_CLAIM)
            )
            continue
        assessments.append(
            assess_record(
                record,
                rule=rules.get(str(record["rule_id"])),
                claim=claim,
                provider=provider,
                clock=clock,
            )
        )
    return assessments


def derive_advisory(response: SystemOneResponse) -> AdvisorySummary:
    """Turn one response into the advisory summary, or refuse an answer we did not ask for.

    Every derivation is positional and explicit: the grounding probability, the
    named choice with its confidence, and the attention score mapped to the level
    at that position. An answer of the wrong *type*, a choice name we never
    offered, or a score off the scale is a malformed answer, not something to
    interpret — it raises :class:`~claimguard.edu.judge.provider.JudgeResponseError`.
    """
    grounded = response.answer_for(QUESTION_GROUNDED)
    agreement = response.answer_for(QUESTION_STATUS_AGREEMENT)
    attention = response.answer_for(QUESTION_ATTENTION)
    missing = [
        name
        for name, answer in (
            (QUESTION_GROUNDED, grounded),
            (QUESTION_STATUS_AGREEMENT, agreement),
            (QUESTION_ATTENTION, attention),
        )
        if answer is None
    ]
    if grounded is None or agreement is None or attention is None:
        raise JudgeResponseError(f"the model did not answer: {', '.join(missing)}")
    if not isinstance(grounded, NoulAnswer):
        raise JudgeResponseError(f"'{QUESTION_GROUNDED}' answered as {grounded.type}, not noul")
    if not isinstance(agreement, ChoiceAnswer):
        raise JudgeResponseError(
            f"'{QUESTION_STATUS_AGREEMENT}' answered as {agreement.type}, not choice"
        )
    if not isinstance(attention, ScoreAnswer):
        raise JudgeResponseError(f"'{QUESTION_ATTENTION}' answered as {attention.type}, not score")
    try:
        choice = AgreementChoice(agreement.choice)
    except ValueError as exc:
        raise JudgeResponseError(f"unknown agreement choice: {agreement.choice!r}") from exc
    return AdvisorySummary(
        grounded_probability=grounded.noul,
        agreement=choice,
        agreement_confidence=agreement.confidence,
        attention_score=attention.score,
        attention_level=_attention_level(attention.score),
    )


def _attention_level(score: float) -> AttentionLevel:
    """Map an attention score to the level at that position, refusing an off-scale score."""
    levels = list(AttentionLevel)
    index = int(score)
    if score != index or not 0 <= index < len(levels):
        raise JudgeResponseError(
            f"attention score {score} is not a level position in 0..{len(levels) - 1}"
        )
    return levels[index]


def _assessed(
    claim_id: str,
    rule_id: str,
    provider: JudgeProvider,
    response: SystemOneResponse,
    questions: Mapping[str, Question],
    latency_ms: float,
) -> JudgeAssessment:
    """Build an ``assessed`` record; a malformed answer set makes it ``failed`` instead."""
    try:
        advisory = derive_advisory(response)
    except JudgeError as exc:
        return _failed(
            claim_id,
            rule_id,
            provider,
            str(exc),
            questions=questions,
            answers=response,
            latency_ms=latency_ms,
        )
    return JudgeAssessment(
        claim_id=claim_id,
        rule_id=rule_id,
        status=JudgeStatus.ASSESSED,
        reason=REASON_ASSESSED,
        provider=provider.name,
        model=response.model,
        questions=dict(questions),
        answers=dict(response.answers),
        advisory=advisory,
        usage=response.usage,
        latency_ms=latency_ms,
    )


def _skipped(claim_id: str, rule_id: str, provider: JudgeProvider, reason: str) -> JudgeAssessment:
    """A finding that was deliberately not sent anywhere."""
    return JudgeAssessment(
        claim_id=claim_id,
        rule_id=rule_id,
        status=JudgeStatus.SKIPPED,
        reason=reason,
        provider=provider.name,
    )


def _failed(
    claim_id: str,
    rule_id: str,
    provider: JudgeProvider,
    reason: str,
    *,
    questions: Mapping[str, Question] | None = None,
    answers: SystemOneResponse | None = None,
    latency_ms: float = 0.0,
) -> JudgeAssessment:
    """A judge fault: recorded with its reason, and inert everywhere else."""
    return JudgeAssessment(
        claim_id=claim_id,
        rule_id=rule_id,
        status=JudgeStatus.FAILED,
        reason=reason,
        provider=provider.name,
        model=answers.model if answers is not None else None,
        questions=dict(questions or {}),
        answers=dict(answers.answers) if answers is not None else {},
        usage=answers.usage if answers is not None else None,
        latency_ms=latency_ms,
    )


def usage_of(assessments: Sequence[JudgeAssessment]) -> Usage | None:
    """Total token usage across assessments that were actually sent (``None`` when none was)."""
    sent = [assessment.usage for assessment in assessments if assessment.usage is not None]
    if not sent:
        return None
    return Usage(
        input_tokens=sum(usage.input_tokens for usage in sent),
        output_tokens=sum(usage.output_tokens for usage in sent),
    )
