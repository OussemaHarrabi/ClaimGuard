"""The runner: one record in, one inert assessment out.

Every judge failure mode is exercised here, and each one must end in a ``failed``
assessment with a reason and no other effect. The offline path is proved twice
over: the injected transport is never invoked *and* ``urlopen`` has been replaced
by a bomb.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from claimguard.edu.judge.models import (
    AdvisorySummary,
    AgreementChoice,
    AttentionLevel,
    JudgeStatus,
    SystemOneResponse,
)
from claimguard.edu.judge.provider import (
    JevJudge,
    JudgeHTTPError,
    JudgeProvider,
    JudgeResponseError,
    JudgeTransportError,
    NullJudge,
)
from claimguard.edu.judge.run import (
    REASON_ASSESSED,
    REASON_EVIDENCE,
    REASON_NO_CLAIM,
    REASON_NO_RULE,
    assess_record,
    assess_records,
    derive_advisory,
    usage_of,
)

from tests.judge import (
    MODEL,
    FakeTransport,
    failing,
    forbid_network,
    rule_for,
    sample,
    settings,
    systemone_body,
)


def clock_at(*values: float) -> Callable[[], float]:
    """A deterministic clock that yields ``values`` in order."""
    ticks: Iterator[float] = iter(values)
    return lambda: next(ticks)


def judge(transport: FakeTransport) -> JevJudge:
    """A real provider wired to a fake transport."""
    return JevJudge(settings(), transport=transport)


# ---------------------------------------------------------------------------
# A full assessment
# ---------------------------------------------------------------------------


def test_a_full_assessment_derives_the_advisory_summary() -> None:
    record, claim = sample()
    transport = FakeTransport(body=systemone_body(grounded=0.94, choice="agree", score=1.0))
    assessment = assess_record(
        record, rule=rule_for(), claim=claim, provider=judge(transport), clock=clock_at(2.0, 2.25)
    )
    assert assessment.status is JudgeStatus.ASSESSED
    assert assessment.reason == REASON_ASSESSED
    assert assessment.provider == "jev"
    assert assessment.model == MODEL
    assert assessment.advisory == AdvisorySummary(
        grounded_probability=0.94,
        agreement=AgreementChoice.AGREE,
        agreement_confidence=0.82,
        attention_score=1.0,
        attention_level=AttentionLevel.THIS_WEEK,
    )
    assert assessment.usage is not None
    assert (assessment.usage.input_tokens, assessment.usage.output_tokens) == (512, 24)
    assert assessment.latency_ms == pytest.approx(250.0)
    assert assessment.key == (record["claim_id"], record["rule_id"])


def test_the_assessment_keeps_the_raw_questions_and_answers() -> None:
    record, claim = sample()
    assessment = assess_record(
        record, rule=rule_for(), claim=claim, provider=judge(FakeTransport(systemone_body()))
    )
    assert set(assessment.questions) == {"grounded", "status_agreement", "attention"}
    assert set(assessment.answers) == {"grounded", "status_agreement", "attention"}
    dumped = assessment.model_dump(mode="json")
    assert dumped["questions"]["grounded"]["type"] == "noul"
    assert dumped["answers"]["attention"]["score"] == 1.0


def test_a_failing_record_is_judged_on_its_own_values() -> None:
    record, claim = failing()
    transport = FakeTransport(body=systemone_body(choice="disagree", score=2.0))
    assessment = assess_record(
        record, rule=rule_for("R008"), claim=claim, provider=judge(transport)
    )
    assert assessment.status is JudgeStatus.ASSESSED
    assert assessment.advisory.agreement is AgreementChoice.DISAGREE
    assert assessment.advisory.attention_level is AttentionLevel.TODAY
    payload = transport.payloads[0]
    assert payload["state"]["finding"]["status"] == "FAIL"
    assert payload["state"]["finding"]["requires_human_review"] is True


def test_the_attention_score_maps_to_the_level_at_that_position() -> None:
    for score, level in enumerate(AttentionLevel):
        record, claim = sample()
        assessment = assess_record(
            record,
            rule=rule_for(),
            claim=claim,
            provider=judge(FakeTransport(systemone_body(score=float(score)))),
        )
        assert assessment.advisory.attention_level is level


# ---------------------------------------------------------------------------
# No key: nothing is sent, everything is skipped
# ---------------------------------------------------------------------------


def test_without_a_key_nothing_is_sent_and_every_record_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network = forbid_network(monkeypatch)
    transport = FakeTransport(body=systemone_body())
    records, claims = [sample()[0], failing()[0]], [sample()[1], failing()[1]]
    assessments = assess_records(
        records,
        rules={"R001": rule_for(), "R008": rule_for("R008")},
        claims={claim["claim_id"]: claim for claim in claims},
        provider=NullJudge(),
    )
    assert [assessment.status for assessment in assessments] == [
        JudgeStatus.SKIPPED,
        JudgeStatus.SKIPPED,
    ]
    assert all("no API key" in assessment.reason for assessment in assessments)
    assert all(assessment.advisory == AdvisorySummary() for assessment in assessments)
    assert not transport.called, "the injected transport was never invoked"
    assert network == [], "urlopen was never called either"


def test_a_disabled_judge_is_a_skip_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_network(monkeypatch)
    record, claim = sample()
    assessment = assess_record(record, rule=rule_for(), claim=claim, provider=NullJudge())
    assert assessment.status is JudgeStatus.SKIPPED
    assert assessment.provider == "null"
    assert assessment.answers == {}


# ---------------------------------------------------------------------------
# Every failure mode is inert
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "transport"),
    [
        ("timeout", FakeTransport(error=TimeoutError("timed out"))),
        ("connection", FakeTransport(error=OSError("connection reset"))),
        ("422", FakeTransport(error=JudgeHTTPError(422, "validation"))),
        ("500", FakeTransport(error=JudgeHTTPError(500, "server error"))),
        ("non-json", FakeTransport(body="<html>502</html>")),
        (
            "unknown-answer-type",
            FakeTransport(
                body=systemone_body(answers={"grounded": {"type": "ranking", "order": ["a"]}})
            ),
        ),
        ("no-usage", FakeTransport(body=systemone_body().replace('"usage"', '"tokens"'))),
    ],
)
def test_a_judge_fault_is_recorded_as_failed_and_changes_nothing(
    label: str, transport: FakeTransport
) -> None:
    record, claim = sample()
    before = json.dumps(record, sort_keys=True)
    assessment = assess_record(record, rule=rule_for(), claim=claim, provider=judge(transport))
    assert assessment.status is JudgeStatus.FAILED, label
    assert assessment.reason, "a failure always carries its reason"
    assert assessment.advisory == AdvisorySummary()
    assert json.dumps(record, sort_keys=True) == before
    assert assessment.key == (record["claim_id"], record["rule_id"])


def test_an_unanswered_question_is_a_failure() -> None:
    body = systemone_body(answers={"grounded": {"type": "noul", "noul": 0.9}})
    record, claim = sample()
    assessment = assess_record(
        record, rule=rule_for(), claim=claim, provider=judge(FakeTransport(body=body))
    )
    assert assessment.status is JudgeStatus.FAILED
    assert "status_agreement" in assessment.reason and "attention" in assessment.reason


def test_a_choice_we_never_offered_is_a_failure() -> None:
    body = systemone_body(choice="maybe")
    record, claim = sample()
    assessment = assess_record(
        record, rule=rule_for(), claim=claim, provider=judge(FakeTransport(body=body))
    )
    assert assessment.status is JudgeStatus.FAILED
    assert "unknown agreement choice" in assessment.reason


@pytest.mark.parametrize("score", [3.0, 1.5])
def test_an_off_scale_attention_score_is_a_failure(score: float) -> None:
    record, claim = sample()
    assessment = assess_record(
        record,
        rule=rule_for(),
        claim=claim,
        provider=judge(FakeTransport(body=systemone_body(score=score))),
    )
    assert assessment.status is JudgeStatus.FAILED
    assert "attention score" in assessment.reason


def test_an_answer_of_the_wrong_type_for_its_question_is_a_failure() -> None:
    body = systemone_body(answers={"grounded": {"type": "noul", "noul": 0.9}})
    response = SystemOneResponse.model_validate(json.loads(body))
    with pytest.raises(JudgeResponseError, match="did not answer"):
        derive_advisory(response)


def test_an_unexpected_provider_fault_is_still_inert() -> None:
    """A provider that breaks its own contract cannot break the run."""

    class Exploding:
        name = "exploding"

        def assess(self, state: Any, questions: Any) -> SystemOneResponse:
            raise RuntimeError("boom")

        def list_models(self) -> list[str]:
            return []

    record, claim = sample()
    provider: JudgeProvider = Exploding()
    assessment = assess_record(record, rule=rule_for(), claim=claim, provider=provider)
    assert assessment.status is JudgeStatus.FAILED
    assert assessment.reason == "unexpected judge failure: RuntimeError"
    assert "boom" not in assessment.reason, "an unknown fault contributes no message of its own"


def test_a_transport_error_keeps_its_typed_reason() -> None:
    record, claim = sample()
    assessment = assess_record(
        record,
        rule=rule_for(),
        claim=claim,
        provider=judge(FakeTransport(error=JudgeTransportError("endpoint unreachable: refused"))),
    )
    assert assessment.status is JudgeStatus.FAILED
    assert "unreachable" in assessment.reason


# ---------------------------------------------------------------------------
# What is never sent
# ---------------------------------------------------------------------------


def test_a_finding_whose_evidence_does_not_verify_is_never_sent() -> None:
    record, claim = sample()
    record["evidence"][0]["value"] = "TAMPERED"
    transport = FakeTransport(body=systemone_body())
    assessment = assess_record(record, rule=rule_for(), claim=claim, provider=judge(transport))
    assert assessment.status is JudgeStatus.SKIPPED
    assert assessment.reason.startswith(REASON_EVIDENCE)
    assert not transport.called


def test_a_rule_missing_from_the_manifest_is_skipped() -> None:
    record, claim = sample()
    transport = FakeTransport(body=systemone_body())
    assessment = assess_record(record, rule=None, claim=claim, provider=judge(transport))
    assert assessment.status is JudgeStatus.SKIPPED
    assert assessment.reason == REASON_NO_RULE
    assert not transport.called


def test_a_claim_that_was_not_supplied_is_skipped() -> None:
    record, _ = sample()
    transport = FakeTransport(body=systemone_body())
    assessments = assess_records(
        [record], rules={"R001": rule_for()}, claims={}, provider=judge(transport)
    )
    assert assessments[0].status is JudgeStatus.SKIPPED
    assert assessments[0].reason == REASON_NO_CLAIM
    assert not transport.called


# ---------------------------------------------------------------------------
# One record in, one assessment out
# ---------------------------------------------------------------------------


def test_every_record_gets_exactly_one_assessment_in_order() -> None:
    pass_record, pass_claim = sample()
    fail_record, fail_claim = failing()
    transport = FakeTransport(body=systemone_body())
    records = [pass_record, fail_record]
    assessments = assess_records(
        records,
        rules={"R001": rule_for(), "R008": rule_for("R008")},
        claims={pass_claim["claim_id"]: pass_claim, fail_claim["claim_id"]: fail_claim},
        provider=judge(transport),
    )
    assert [assessment.key for assessment in assessments] == [
        (pass_record["claim_id"], "R001"),
        (fail_record["claim_id"], "R008"),
    ]
    assert len(transport.requests) == 2


def test_a_whole_run_leaves_the_records_byte_identical() -> None:
    pass_record, pass_claim = sample()
    fail_record, fail_claim = failing()
    records = [pass_record, fail_record]
    before = [json.dumps(record, sort_keys=True) for record in records]
    identities = [id(record) for record in records]
    keys = [set(record) for record in records]
    assess_records(
        records,
        rules={"R001": rule_for(), "R008": rule_for("R008")},
        claims={pass_claim["claim_id"]: pass_claim, fail_claim["claim_id"]: fail_claim},
        provider=judge(FakeTransport(body=systemone_body())),
    )
    assert [json.dumps(record, sort_keys=True) for record in records] == before
    assert [id(record) for record in records] == identities, "same objects, not copies"
    assert [set(record) for record in records] == keys, "same 15 keys, no judge field added"


def test_usage_is_totalled_across_the_assessments_that_were_sent() -> None:
    pass_record, pass_claim = sample()
    fail_record, fail_claim = failing()
    assessments = assess_records(
        [pass_record, fail_record],
        rules={"R001": rule_for(), "R008": rule_for("R008")},
        claims={pass_claim["claim_id"]: pass_claim, fail_claim["claim_id"]: fail_claim},
        provider=judge(FakeTransport(body=systemone_body(input_tokens=100, output_tokens=10))),
    )
    usage = usage_of(assessments)
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (200, 20)
    assert usage_of([assessment for assessment in assessments if False]) is None
