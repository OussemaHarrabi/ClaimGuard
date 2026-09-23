"""The sidecar: a round trip, and the structural refusal to merge.

The last test in this file is the one the safety boundary rests on: the graded
records come back from every sidecar function as the same objects with the same
15 keys, and a record that has already been contaminated is refused outright.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from claimguard.edu.envelope import RESULT_KEYS
from claimguard.edu.judge.models import (
    AdvisorySummary,
    AgreementChoice,
    JudgeAssessment,
    JudgeStatus,
)
from claimguard.edu.judge.sidecar import (
    SidecarError,
    append_assessments,
    assert_graded_records,
    index_assessments,
    pair_records,
    read_assessments,
    separate,
    summarize,
    write_assessments,
)

from tests.judge import failing, sample


def assessment(
    claim_id: str, rule_id: str, status: JudgeStatus = JudgeStatus.ASSESSED
) -> JudgeAssessment:
    """One assessment of the given finding."""
    return JudgeAssessment(
        claim_id=claim_id,
        rule_id=rule_id,
        status=status,
        reason="the model answered every question",
        provider="jev",
        model="jev-test-1",
        advisory=AdvisorySummary(grounded_probability=0.9, agreement=AgreementChoice.AGREE),
    )


def test_the_sidecar_round_trips(tmp_path: Any) -> None:
    path = tmp_path / "nested" / "judge.jsonl"
    written = [assessment("CG-1", "R001"), assessment("CG-1", "R002", JudgeStatus.SKIPPED)]
    write_assessments(path, written)
    assert path.is_file()
    assert read_assessments(path) == written


def test_appending_adds_rows_without_rewriting_the_file(tmp_path: Any) -> None:
    path = tmp_path / "judge.jsonl"
    write_assessments(path, [assessment("CG-1", "R001")])
    append_assessments(path, [assessment("CG-2", "R001")])
    assert [entry.key for entry in read_assessments(path)] == [("CG-1", "R001"), ("CG-2", "R001")]


def test_a_defective_sidecar_line_is_an_error_not_a_dropped_row(tmp_path: Any) -> None:
    path = tmp_path / "judge.jsonl"
    path.write_text(
        f"{json.dumps(assessment('CG-1', 'R001').model_dump(mode='json'))}\nnot json\n",
        encoding="utf-8",
    )
    with pytest.raises(SidecarError, match="not a judge assessment"):
        read_assessments(path)


def test_a_missing_sidecar_is_an_error(tmp_path: Any) -> None:
    with pytest.raises(SidecarError, match="sidecar not found"):
        read_assessments(tmp_path / "absent.jsonl")


def test_assessments_are_indexed_by_claim_and_rule_with_the_newest_winning() -> None:
    first = assessment("CG-1", "R001", JudgeStatus.FAILED)
    newest = assessment("CG-1", "R001")
    indexed = index_assessments([first, newest])
    assert indexed[("CG-1", "R001")] is newest


def test_the_counts_are_per_judge_status() -> None:
    counts = summarize(
        [
            assessment("CG-1", "R001"),
            assessment("CG-1", "R002", JudgeStatus.SKIPPED),
            assessment("CG-2", "R001", JudgeStatus.FAILED),
        ]
    )
    assert counts == {"total": 3, "assessed": 1, "skipped": 1, "failed": 1}


# ---------------------------------------------------------------------------
# The merge guard
# ---------------------------------------------------------------------------


def test_separate_returns_two_disjoint_collections_and_hands_the_records_back_untouched() -> None:
    record, _ = sample()
    fail_record, _ = failing()
    records = [record, fail_record]
    assessments = [assessment(record["claim_id"], "R001")]
    before = [json.dumps(entry, sort_keys=True) for entry in records]
    identities = [id(entry) for entry in records]

    returned_records, returned_assessments = separate(records, assessments)

    assert returned_records is not records, "a new collection, never the caller's list"
    assert [id(entry) for entry in returned_records] == identities, "the same record objects"
    assert [set(entry) for entry in returned_records] == [set(RESULT_KEYS)] * 2
    assert [json.dumps(entry, sort_keys=True) for entry in returned_records] == before
    assert returned_assessments == assessments
    assert not set(map(id, returned_records)) & set(map(id, returned_assessments))
    assert all(isinstance(entry, dict) for entry in returned_records)


def test_a_record_that_has_been_merged_with_judge_output_is_refused() -> None:
    record, _ = sample()
    merged = {**record, "advisory": {"grounded_probability": 0.9}}
    with pytest.raises(SidecarError, match="unexpected: \\['advisory'\\]"):
        separate([merged], [])
    with pytest.raises(SidecarError, match="missing: \\['severity'\\]"):
        separate([{key: value for key, value in record.items() if key != "severity"}], [])


def test_a_record_whose_status_was_overwritten_by_a_judge_status_is_refused() -> None:
    record, _ = sample()
    record["status"] = "assessed"
    with pytest.raises(SidecarError, match="not the frozen result contract"):
        assert_graded_records([record])


def test_pairing_is_a_read_only_view() -> None:
    record, _ = sample()
    fail_record, _ = failing()
    records = [record, fail_record]
    before = [json.dumps(entry, sort_keys=True) for entry in records]
    paired = pair_records(records, [assessment(fail_record["claim_id"], fail_record["rule_id"])])
    assert [entry for entry, _ in paired] == records
    assert paired[0][1] is None
    assert paired[1][1] is not None
    assert paired[1][1].key == (fail_record["claim_id"], fail_record["rule_id"])
    assert [json.dumps(entry, sort_keys=True) for entry in records] == before
