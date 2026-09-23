"""The sidecar: where judge output lives, and why it cannot reach a result record.

The graded contract has exactly 15 keys and the mentor's scorer rejects any extra
or missing one. Judge output therefore lives in its own JSONL file, keyed by
``(claim_id, rule_id)``, and this module is the only door between the two:

*   :func:`write_assessments` / :func:`append_assessments` — write the sidecar;
*   :func:`read_assessments` — read it back, strictly (a malformed line is an
    error, never a silently dropped row);
*   :func:`index_assessments` — key assessments by ``(claim_id, rule_id)``;
*   :func:`pair_records` — a read-only *view* joining records to assessments;
*   :func:`separate` — the guarded split that hands the records back untouched.

:func:`separate` and :func:`assert_graded_records` are the structural guarantee:
they refuse any record whose key set is not exactly the frozen 15, so a merged
record (a ``status`` overwritten by a judge status, an ``advisory`` block added,
a ``severity`` nudged) cannot pass through this module at all. Merging is not
discouraged here; it is unimplementable.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import ValidationError

from claimguard.edu.emit import ContractError, validate_record
from claimguard.edu.envelope import RESULT_KEYS, Result
from claimguard.edu.judge.models import JudgeAssessment


class SidecarError(ValueError):
    """The sidecar file is unreadable, or a record is not the frozen 15-key contract."""


def _line(assessment: JudgeAssessment) -> str:
    """One assessment as a single JSON object line."""
    return json.dumps(assessment.model_dump(mode="json"), ensure_ascii=False)


def write_assessments(path: str | Path, assessments: Iterable[JudgeAssessment]) -> Path:
    """Write the sidecar from scratch (one JSON object per line), returning its path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{_line(assessment)}\n" for assessment in assessments)
    target.write_text(text, encoding="utf-8")
    return target


def append_assessments(path: str | Path, assessments: Iterable[JudgeAssessment]) -> Path:
    """Append assessments to the sidecar, creating it (and its directory) when needed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for assessment in assessments:
            handle.write(f"{_line(assessment)}\n")
    return target


def read_assessments(path: str | Path) -> list[JudgeAssessment]:
    """Read a sidecar back into typed assessments; a defective line is an error."""
    target = Path(path)
    if not target.is_file():
        raise SidecarError(f"sidecar not found: {target}")
    assessments: list[JudgeAssessment] = []
    for number, raw in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            assessments.append(JudgeAssessment.model_validate_json(raw))
        except ValidationError as exc:
            raise SidecarError(f"{target}:{number}: not a judge assessment: {exc}") from exc
    return assessments


def index_assessments(
    assessments: Iterable[JudgeAssessment],
) -> dict[tuple[str, str], JudgeAssessment]:
    """Assessments keyed by ``(claim_id, rule_id)``; on a repeated pair the last one wins.

    Re-running the judge appends, so a pair legitimately appears more than once.
    The last occurrence is the newest assessment of that finding.
    """
    return {assessment.key: assessment for assessment in assessments}


def assert_graded_records(records: Iterable[Result]) -> None:
    """Refuse any record that is not exactly the frozen 15-key result contract.

    This is the merge guard, and it is two checks deep: the key set must be
    exactly the frozen 15 (so no judge field can be added and none removed), and
    the record must still validate against the contract (so no field can be
    overwritten with a judge value — a judge ``status`` of ``assessed`` is not a
    claim status, and the contract says so).
    """
    for record in records:
        keys = set(record)
        if keys != set(RESULT_KEYS):
            missing = sorted(set(RESULT_KEYS) - keys)
            unexpected = sorted(keys - set(RESULT_KEYS))
            raise SidecarError(
                "record is not the frozen result contract "
                f"(missing: {missing or 'none'}; unexpected: {unexpected or 'none'})"
            )
        try:
            validate_record(record)
        except ContractError as exc:
            raise SidecarError(f"record is not the frozen result contract: {exc}") from exc


def separate(
    records: Sequence[Result], assessments: Iterable[JudgeAssessment]
) -> tuple[list[Result], list[JudgeAssessment]]:
    """Return the graded records and the judge assessments as two disjoint collections.

    The records come back as the *same objects*, in the same order, with the same
    keys — this function has no return path that could carry an assessment into a
    record, and it refuses a record that has already been contaminated.
    """
    assert_graded_records(records)
    return list(records), list(assessments)


def pair_records(
    records: Sequence[Result], assessments: Iterable[JudgeAssessment]
) -> list[tuple[Result, JudgeAssessment | None]]:
    """A read-only view pairing each record with its assessment (``None`` when absent).

    The tuple is a convenience for reporting, never a merge step: the record half
    is the original object and nothing writes through it.
    """
    assert_graded_records(records)
    by_key = index_assessments(assessments)
    return [(record, by_key.get(_record_key(record))) for record in records]


def _record_key(record: Result) -> tuple[str, str]:
    """The ``(claim_id, rule_id)`` pair of one graded record."""
    return (str(record["claim_id"]), str(record["rule_id"]))


def summarize(assessments: Iterable[JudgeAssessment]) -> dict[str, int]:
    """Counts per judge status, for a run report (``{"assessed": n, ...}``)."""
    counts: dict[str, int] = {"total": 0, "assessed": 0, "skipped": 0, "failed": 0}
    for assessment in assessments:
        counts["total"] += 1
        counts[str(assessment.status)] = counts.get(str(assessment.status), 0) + 1
    return counts
