"""The question builder: three questions, one record, nothing else sent.

The builder is pure, so it is tested without a provider, a key or a network. The
records it is tested with are real engine records over the vendored catalogue,
which is what makes these tests runnable in CI without the mentor pack.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from claimguard.edu.envelope import RESULT_KEYS
from claimguard.edu.judge.models import (
    AgreementChoice,
    AttentionLevel,
    ChoiceQuestion,
    NoulQuestion,
    ScoreQuestion,
    SystemOneRequest,
)
from claimguard.edu.judge.questions import (
    QUESTION_ATTENTION,
    QUESTION_GROUNDED,
    QUESTION_NAMES,
    QUESTION_STATUS_AGREEMENT,
    RULE_EXCERPT_CHARS,
    QuestionError,
    build_body,
    build_questions,
    build_state,
    rule_excerpt,
)
from claimguard.edu.policy import RuleMeta

from tests.judge import API_KEY, MODEL, failing, rule_for, sample


def test_the_three_questions_are_built_from_a_real_record() -> None:
    record, _ = sample()
    questions = build_questions(record)
    assert list(questions) == list(QUESTION_NAMES)
    assert isinstance(questions[QUESTION_GROUNDED], NoulQuestion)
    assert isinstance(questions[QUESTION_STATUS_AGREEMENT], ChoiceQuestion)
    assert isinstance(questions[QUESTION_ATTENTION], ScoreQuestion)


def test_the_second_opinion_question_offers_exactly_the_three_named_choices() -> None:
    questions = build_questions(sample()[0])
    question = questions[QUESTION_STATUS_AGREEMENT]
    assert isinstance(question, ChoiceQuestion)
    assert list(question.criteria) == [choice.value for choice in AgreementChoice]


def test_the_attention_question_is_an_ordered_scale_whose_position_is_the_score() -> None:
    questions = build_questions(sample()[0])
    question = questions[QUESTION_ATTENTION]
    assert isinstance(question, ScoreQuestion)
    assert len(question.criteria) == len(AttentionLevel)
    for position, level in enumerate(AttentionLevel):
        assert str(question.criteria[position]).startswith(level.value)


def test_the_questions_name_the_finding_they_are_about() -> None:
    record, _ = failing()
    questions = build_questions(record)
    grounded = questions[QUESTION_GROUNDED]
    assert isinstance(grounded, NoulQuestion)
    instructions = str(grounded.instructions)
    assert record["claim_id"] in instructions
    assert record["rule_id"] in instructions
    assert record["status"] in instructions


def test_the_state_carries_the_record_its_evidence_and_a_rule_excerpt_only() -> None:
    record, _ = sample()
    state = build_state(record, rule_for())
    assert list(state) == ["finding", "evidence", "rule_excerpt"]
    assert list(state["finding"]) == list(RESULT_KEYS), "the record's own keys, unchanged"
    assert state["finding"]["claim_id"] == record["claim_id"]
    assert state["evidence"] == [dict(entry) for entry in record["evidence"]]
    assert set(state["rule_excerpt"]) <= {
        "rule_id",
        "title",
        "severity",
        "logic",
        "corrective_action",
        "version",
        "source",
    }


def test_the_state_sends_no_credential_and_nothing_outside_the_record() -> None:
    record, _ = sample()
    body = build_body(MODEL, record, rule_for())
    text = json.dumps(body)
    assert API_KEY not in text
    assert "patient_id" not in text or "patient_id" in json.dumps(record)
    assert set(body) == {"model", "state", "questions"}


def test_a_long_rule_is_truncated_to_the_excerpt_bound() -> None:
    rule = rule_for()
    long_rule = RuleMeta.model_validate(
        {**rule.model_dump(), "logic": "x" * (RULE_EXCERPT_CHARS * 2)}
    )
    excerpt = rule_excerpt(long_rule)
    assert len(str(excerpt["logic"])) == RULE_EXCERPT_CHARS


def test_a_record_that_is_not_the_frozen_contract_is_refused() -> None:
    record, _ = sample()
    with pytest.raises(QuestionError, match="non-contract keys"):
        build_state({**record, "advisory": {"grounded_probability": 0.9}}, rule_for())
    missing = {key: value for key, value in record.items() if key != "severity"}
    with pytest.raises(QuestionError, match="missing contract keys"):
        build_state(missing, rule_for())


def test_the_builder_is_pure_and_repeatable() -> None:
    record, _ = sample()
    before = json.dumps(record, sort_keys=True)
    first = build_body(MODEL, record, rule_for())
    second = build_body(MODEL, record, rule_for())
    assert first == second
    assert json.dumps(record, sort_keys=True) == before, "the record is never an output"


def test_the_body_round_trips_through_the_contract_model() -> None:
    record, _ = sample()
    body = build_body(MODEL, record, rule_for())
    parsed = SystemOneRequest.model_validate(body)
    assert parsed.model == MODEL
    assert list(parsed.questions) == list(QUESTION_NAMES)


def test_every_question_carries_only_the_documented_fields() -> None:
    body = build_body(MODEL, sample()[0], rule_for())
    allowed = {"type", "instructions", "criteria"}
    for name, question in body["questions"].items():
        assert set(question) <= allowed, f"{name} carries an undocumented field"
        assert question["type"] in {"noul", "choice", "score"}
    assert body["questions"]["grounded"]["criteria"] == {
        "true": "every statement in the explanation is supported by the cited evidence",
        "false": (
            "at least one statement is unsupported by, contradicted by, or goes beyond the "
            "cited evidence"
        ),
    }


def test_the_state_is_plain_json_for_a_failing_record_too() -> None:
    record, _ = failing()
    body = build_body(MODEL, record, rule_for("R008"))
    state: Any = body["state"]
    assert json.loads(json.dumps(state)) == state
    assert state["finding"]["status"] == "FAIL"
    assert state["evidence"], "a FAIL record cites the evidence that proves it"
