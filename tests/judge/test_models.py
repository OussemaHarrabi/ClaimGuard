"""The contract mirror: exactly the vendor's fields, and no others.

These tests defend the one thing that makes the layer trustworthy — the payload
we build is the payload the API documents. ``extra="forbid"`` is asserted from
both sides: our own requests can never carry an undocumented field, and a
response that carries one is refused rather than half-read.
"""

from __future__ import annotations

import pytest
from claimguard.edu.judge.models import (
    AdvisorySummary,
    AgreementChoice,
    AttentionLevel,
    ChoiceAnswer,
    ChoiceQuestion,
    JudgeAssessment,
    JudgeStatus,
    ModelsResponse,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
    SystemOneRequest,
    SystemOneResponse,
)
from pydantic import ValidationError

NoulPayload = {
    "type": "noul",
    "instructions": "Is it so?",
    "criteria": {"true": "yes", "false": "no"},
}
ChoicePayload = {
    "type": "choice",
    "criteria": {"agree": "it is right", "disagree": "it is wrong"},
}
ScorePayload = {"type": "score", "criteria": ["low", "high"]}


def request(questions: dict[str, object]) -> SystemOneRequest:
    """A minimal request envelope around ``questions``."""
    return SystemOneRequest(model="jev-latest", state={"finding": {}}, questions=questions)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------


def test_each_question_variant_is_discriminated_by_its_type() -> None:
    parsed = request({"q": NoulPayload})  # type: ignore[dict-item]
    assert isinstance(parsed.questions["q"], NoulQuestion)

    parsed = request({"q": ChoicePayload})  # type: ignore[dict-item]
    assert isinstance(parsed.questions["q"], ChoiceQuestion)

    parsed = request({"q": ScorePayload})  # type: ignore[dict-item]
    assert isinstance(parsed.questions["q"], ScoreQuestion)


def test_an_unknown_question_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        request({"q": {"type": "ranking", "criteria": ["a"]}})  # type: ignore[dict-item]


def test_a_question_with_an_undocumented_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        request({"q": {**NoulPayload, "temperature": 0.2}})  # type: ignore[dict-item]


def test_choice_criteria_are_required_and_non_empty() -> None:
    with pytest.raises(ValidationError):
        ChoiceQuestion.model_validate({"type": "choice", "instructions": "pick one"})
    with pytest.raises(ValidationError):
        ChoiceQuestion(type="choice", criteria={})


def test_score_criteria_are_an_ordered_non_empty_list() -> None:
    with pytest.raises(ValidationError):
        ScoreQuestion(type="score", criteria=[])
    question = ScoreQuestion(type="score", criteria=["can wait", "today"])
    assert question.criteria == ["can wait", "today"], "position is the score, so order is kept"


def test_noul_criteria_are_optional() -> None:
    assert NoulQuestion(type="noul", instructions="Is it so?").criteria is None


def test_state_and_instructions_accept_any_json_value_but_nothing_else() -> None:
    assert SystemOneRequest(model="m", state=[1, {"a": None}], questions={"q": NoulPayload}).state  # type: ignore[dict-item]
    with pytest.raises(ValidationError):
        SystemOneRequest(model="m", state={1, 2}, questions={"q": NoulPayload})  # type: ignore[dict-item]
    with pytest.raises(ValidationError):
        NoulQuestion(type="noul", instructions=object())


def test_the_request_requires_all_three_documented_fields() -> None:
    with pytest.raises(ValidationError):
        SystemOneRequest.model_validate({"model": "m", "state": {}})
    with pytest.raises(ValidationError):
        SystemOneRequest(model="m", state={}, questions={})


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------


def test_each_answer_variant_parses_into_its_own_model() -> None:
    answers: dict[str, object] = {
        "grounded": {"type": "noul", "noul": 0.9},
        "status_agreement": {
            "type": "choice",
            "choice": "agree",
            "confidence": 0.8,
            "probabilities": {"agree": 0.8, "disagree": 0.2},
        },
        "attention": {
            "type": "score",
            "score": 2.0,
            "confidence": 0.7,
            "legend": {"2": "needs attention today"},
            "probabilities": {"2": 0.7},
        },
    }
    response = SystemOneResponse.model_validate(
        {
            "model": "jev-latest",
            "answers": answers,
            "usage": {"input_tokens": 10, "output_tokens": 0},
        }
    )
    assert isinstance(response.answer_for("grounded"), NoulAnswer)
    assert isinstance(response.answer_for("status_agreement"), ChoiceAnswer)
    assert isinstance(response.answer_for("attention"), ScoreAnswer)
    assert response.answer_for("never_asked") is None


def test_an_unknown_answer_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SystemOneResponse.model_validate(
            {
                "model": "jev-latest",
                "answers": {"q": {"type": "ranking", "order": ["a", "b"]}},
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        )


def test_a_selected_choice_absent_from_its_probabilities_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ChoiceAnswer(type="choice", choice="agree", confidence=0.9, probabilities={"disagree": 1.0})


def test_probabilities_outside_zero_to_one_are_rejected() -> None:
    with pytest.raises(ValidationError):
        NoulAnswer(type="noul", noul=1.4)
    with pytest.raises(ValidationError):
        NoulAnswer(type="noul", noul=-0.1)


def test_the_response_envelope_requires_usage_and_at_least_one_answer() -> None:
    with pytest.raises(ValidationError):
        SystemOneResponse.model_validate({"model": "jev-latest", "answers": {}})
    with pytest.raises(ValidationError):
        SystemOneResponse.model_validate(
            {"model": "jev-latest", "answers": {"q": {"type": "noul", "noul": 0.5}}}
        )


def test_the_model_list_is_parsed_strictly() -> None:
    parsed = ModelsResponse.model_validate(
        {"models": [{"name": "jev-latest", "description": "d", "release_date": "2026-09-01"}]}
    )
    assert parsed.models[0].name == "jev-latest"
    with pytest.raises(ValidationError):
        ModelsResponse.model_validate({"models": [{"name": "jev-latest", "context_window": 128}]})


# ---------------------------------------------------------------------------
# The advisory record
# ---------------------------------------------------------------------------


def test_an_assessment_is_keyed_by_claim_and_rule_and_is_never_a_result() -> None:
    assessment = JudgeAssessment(
        claim_id="CG-1",
        rule_id="R004",
        status=JudgeStatus.SKIPPED,
        reason="judge disabled",
        provider="null",
    )
    assert assessment.key == ("CG-1", "R004")
    assert not assessment.assessed
    assert assessment.model_dump()["status"] == "skipped"


def test_the_advisory_summary_is_empty_until_a_model_answers() -> None:
    summary = AdvisorySummary()
    assert summary.grounded_probability is None
    assert summary.agreement is None
    assert summary.attention_level is None


def test_the_shared_vocabularies_match_the_questions_we_ask() -> None:
    assert [choice.value for choice in AgreementChoice] == [
        "agree",
        "agree_but_low_confidence",
        "disagree",
    ]
    assert [level.value for level in AttentionLevel] == [
        "can wait",
        "needs attention this week",
        "needs attention today",
    ]
