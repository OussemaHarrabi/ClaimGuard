"""End-to-end checks of the report generator against the mentor pack.

The pack is delivered reference material and is not tracked in git, so these tests skip cleanly
when it is absent (the same ``requires_pack`` guard as ``tests/edu_conformance``; reimplemented
here on purpose so neither test package depends on the other). What they prove, when it is
present:

* a predictions file the mentor's scorer rejects produces **no report** and a refusal (exit 2);
* every headline number in the written report equals the value in the scorer's own metrics JSON;
* the required sections and honesty statements survive into the real artefact.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts import edu_report

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_ROOT = REPO_ROOT / "ClaimGuardAI_Student_Starter_Pack" / "ClaimGuardAI_Student_Starter_Pack"
GENERATOR = REPO_ROOT / "scripts" / "edu_report.py"

requires_pack = pytest.mark.skipif(
    not (PACK_ROOT / "src" / "evaluate.py").is_file(),
    reason="mentor starter pack absent (delivered reference material, not tracked in git)",
)

#: A smaller split keeps the engine run and the oracle cheap; the generator is split-agnostic.
SPLIT = "stress"


def run_generator(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the generator exactly as an operator would."""
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        [sys.executable, str(GENERATOR), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.fixture(scope="module")
def baseline_predictions(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    """The pack's own baseline predictions for the split, as JSON lines (a valid file to mutate)."""
    output = tmp_path_factory.mktemp("baseline") / "baseline.jsonl"
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        [
            sys.executable,
            str(PACK_ROOT / "src" / "run_baseline.py"),
            "--input",
            str(PACK_ROOT / "data" / SPLIT / "claims.jsonl"),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    return lines


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One real generator run over the split, returning its artefacts for the assertions."""
    workdir = tmp_path_factory.mktemp("report")
    output = workdir / "REPORT.md"
    completed = run_generator(
        "--split",
        SPLIT,
        "--output",
        str(output),
        "--workdir",
        str(workdir),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    metrics_path = workdir / SPLIT / "metrics.json"
    context_path = workdir / SPLIT / "report_context.json"
    assert metrics_path.is_file()
    assert context_path.is_file()
    return {
        "stdout": completed.stdout,
        "report": output.read_text(encoding="utf-8"),
        "metrics": json.loads(metrics_path.read_text(encoding="utf-8")),
        "context": json.loads(context_path.read_text(encoding="utf-8")),
    }


def _write(lines: list[str], destination: Path) -> Path:
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


# ---------------------------------------------------------------------------------------
# Refusal: a rejected run is not a result
# ---------------------------------------------------------------------------------------


@requires_pack
def test_generator_refuses_a_rejected_prediction_file(
    baseline_predictions: list[str], tmp_path: Path
) -> None:
    rows: list[dict[str, Any]] = [json.loads(line) for line in baseline_predictions]
    rows[0]["evidence"][0]["value"] = "INVENTED"
    pred = _write([json.dumps(row, ensure_ascii=False) for row in rows], tmp_path / "bad.jsonl")
    output = tmp_path / "REPORT.md"

    completed = run_generator(
        "--split", SPLIT, "--pred", str(pred), "--output", str(output), "--workdir", str(tmp_path)
    )

    assert completed.returncode == edu_report.EXIT_REFUSED
    assert "REFUSED" in completed.stdout
    assert "REJECTED" in completed.stdout
    # The scorer's own words are surfaced verbatim...
    assert "Evaluation rejected" in completed.stdout
    assert "Evidence value mismatch" in completed.stdout
    # ...and nothing was written: a report would have been an endorsement.
    assert not output.exists()


@requires_pack
def test_generator_refuses_an_incomplete_prediction_file(
    baseline_predictions: list[str], tmp_path: Path
) -> None:
    pred = _write(baseline_predictions[:-1], tmp_path / "missing_pair.jsonl")
    output = tmp_path / "REPORT.md"

    completed = run_generator(
        "--split", SPLIT, "--pred", str(pred), "--output", str(output), "--workdir", str(tmp_path)
    )

    assert completed.returncode == edu_report.EXIT_REFUSED
    assert "Prediction coverage mismatch" in completed.stdout
    assert not output.exists()


@requires_pack
def test_generator_refuses_a_missing_predictions_file(tmp_path: Path) -> None:
    output = tmp_path / "REPORT.md"
    completed = run_generator(
        "--split",
        SPLIT,
        "--pred",
        str(tmp_path / "absent.jsonl"),
        "--output",
        str(output),
        "--workdir",
        str(tmp_path),
    )
    assert completed.returncode == edu_report.EXIT_REFUSED
    assert "predictions file not found" in completed.stdout
    assert not output.exists()


# ---------------------------------------------------------------------------------------
# The written report
# ---------------------------------------------------------------------------------------


@requires_pack
def test_report_metrics_match_the_scorers_json(generated: dict[str, Any]) -> None:
    report: str = generated["report"]
    metrics: dict[str, Any] = generated["metrics"]
    overall: dict[str, Any] = metrics["overall"]

    # The generator scores what it wrote: its own context carries the oracle's metrics unchanged.
    assert generated["context"]["metrics"] == metrics
    assert generated["context"]["scorer"]["exit_code"] == 0

    values = {cells[0]: cells[1] for cells in _table_rows(report, "| Metric | Value |")}
    assert values["Claim-rule pairs scored"] == edu_report.fmt_int(overall["count"])
    assert values["True positives (expected FAIL, predicted FAIL)"] == edu_report.fmt_int(
        overall["tp"]
    )
    assert values["False positives"] == edu_report.fmt_int(overall["fp"])
    assert values["False negatives"] == edu_report.fmt_int(overall["fn"])
    assert values["True negatives (neither side FAIL)"] == edu_report.fmt_int(overall["tn"])
    assert values["Issue precision"] == edu_report.fmt_ratio(overall["issue_precision"])
    assert values["Issue recall"] == edu_report.fmt_ratio(overall["issue_recall"])
    assert values["Issue F1"] == edu_report.fmt_ratio(overall["issue_f1"])
    assert values["False-alarm rate"] == edu_report.fmt_ratio(overall["false_alarm_rate"])
    assert values["Status accuracy"] == edu_report.fmt_ratio(overall["status_accuracy"])
    assert values["False abstentions"] == edu_report.fmt_int(overall["false_abstentions"])
    assert values["Missed abstentions"] == edu_report.fmt_int(overall["missed_abstentions"])
    assert values["NOT_IMPLEMENTED predictions"] == edu_report.fmt_int(overall["not_implemented"])

    claims = generated["context"]["claims"]
    exact = metrics["claims_with_all_statuses_correct"]
    assert values["Claim exact match"] == (
        f"{edu_report.fmt_int(exact)} / {claims} = {edu_report.fmt_ratio(exact / claims)}"
    )

    # The per-rule table is the oracle's own by_rule object, rule for rule.
    rows = {cells[0]: cells for cells in _table_rows(report, "| Rule | n | Expected FAIL |")}
    assert set(rows) == set(metrics["by_rule"])
    for rule_id, entry in metrics["by_rule"].items():
        cells = rows[rule_id]
        assert cells[1] == edu_report.fmt_int(entry["count"])
        assert cells[3] == edu_report.fmt_int(entry["tp"])
        assert cells[4] == edu_report.fmt_int(entry["fp"])
        assert cells[5] == edu_report.fmt_int(entry["fn"])
        assert cells[6] == edu_report.fmt_int(entry["tn"])
        assert cells[7] == edu_report.fmt_ratio(entry["issue_precision"])
        assert cells[8] == edu_report.fmt_ratio(entry["issue_recall"])
        assert cells[9] == edu_report.fmt_ratio(entry["issue_f1"])
        assert cells[10] == edu_report.fmt_ratio(entry["false_alarm_rate"])
        assert cells[11] == edu_report.fmt_ratio(entry["status_accuracy"])
        assert cells[12] == edu_report.fmt_int(entry["not_implemented"])

    # ...and the confusion matrix agrees cell for cell, with the unobserved cells zero-filled.
    header = _cells(next(line for line in report.splitlines() if line.startswith("| Expected \\")))
    grid = {cells[0]: cells[1:] for cells in _table_rows(report, "| Expected \\ Predicted |")}
    for item in metrics["confusion"]:
        column = header.index(str(item["predicted"])) - 1
        assert grid[str(item["expected"])][column] == str(item["count"])
    assert sum(int(cell) for cells in grid.values() for cell in cells) == overall["count"]


@requires_pack
def test_report_contains_the_required_sections_and_honesty_rules(
    generated: dict[str, Any],
) -> None:
    report: str = generated["report"]
    for section in edu_report.REQUIRED_SECTIONS:
        assert section in report, section
    for label, _ in edu_report.HONESTY_STATEMENTS:
        assert f"**{label}.**" in report, label
    assert "NOT_IMPLEMENTED counts as incorrect" in report
    assert "instructional oracle" in report
    assert "does not prove that the cited field is relevant" in report
    assert "Explanation quality is not scored by this generator" in report
    assert "cannot discriminate" in report

    # Traceability: the run's own accounting and identity are in the artefact.
    assert edu_report.REPORT_FORMAT_VERSION in report
    assert generated["context"]["engine"]["engine_digest"] in report
    assert generated["context"]["predictions"]["sha256"] in report
    for identity in generated["context"]["dataset"]["inputs"]:
        assert identity["sha256"] in report


@requires_pack
def test_report_records_the_verdict_and_the_support_analysis(generated: dict[str, Any]) -> None:
    report: str = generated["report"]
    context: dict[str, Any] = generated["context"]
    assert "**Verdict: CONFORMANT**" in report
    assert context["failure_reasons"] == []
    assert context["independent"]["problems"] == []
    assert "### Support: which rules carry the thinnest evidence" in report
    supports: list[dict[str, Any]] = context["support"]
    keys = [(item["positives"], item["rule_id"]) for item in supports]
    assert keys == sorted(keys)  # thinnest first, deterministic tie-break
    assert supports[0]["positives"] == min(item["positives"] for item in supports)
    assert "Thinnest positive support" in report
    # Every rule's support row is rendered with its own numbers.
    rows = {cells[0]: cells for cells in _table_rows(report, "| Rule | Expected PASS |")}
    assert set(rows) == {item["rule_id"] for item in supports}
    for item in supports:
        cells = rows[item["rule_id"]]
        assert cells[1] == str(item["expected_pass"])
        assert cells[2] == str(item["expected_fail"])
        assert cells[3] == str(item["expected_unable_to_assess"])
        assert cells[4] == str(item["expected_not_applicable"])
        assert cells[5] == str(item["discriminating_labels"])


@requires_pack
def test_baseline_ablation_runs_when_requested(tmp_path: Path) -> None:
    output = tmp_path / "REPORT.md"
    completed = run_generator(
        "--split",
        SPLIT,
        "--output",
        str(output),
        "--workdir",
        str(tmp_path),
        "--baseline",
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = output.read_text(encoding="utf-8")
    context: dict[str, Any] = json.loads(
        (tmp_path / SPLIT / "report_context.json").read_text(encoding="utf-8")
    )
    baseline: dict[str, Any] = context["baseline"]
    assert baseline is not None
    assert baseline["scorer_exit_code"] == 0
    assert baseline["metrics"], "the ablation must carry the baseline's own metrics"

    rows = {
        cells[0]: cells for cells in _table_rows(report, "| Metric | Our engine | Pack baseline |")
    }
    claims = context["claims"]
    assert rows["Claim exact match"][1] == (
        f"{context['metrics']['claims_with_all_statuses_correct']} / {claims}"
    )
    assert rows["Claim exact match"][2] == (
        f"{baseline['metrics']['claims_with_all_statuses_correct']} / {claims}"
    )
    assert rows["Status accuracy"][1] == edu_report.fmt_ratio(
        context["metrics"]["overall"]["status_accuracy"]
    )
    assert rows["Status accuracy"][2] == edu_report.fmt_ratio(
        baseline["metrics"]["overall"]["status_accuracy"]
    )
    assert rows["NOT_IMPLEMENTED"][2] == edu_report.fmt_int(
        baseline["metrics"]["overall"]["not_implemented"]
    )
    assert "Reference ablation errors" in report
    assert "Implemented: R001, R003, R006" in report  # the baseline's own summary, verbatim


def _table_rows(text: str, header: str) -> list[list[str]]:
    """Data rows (cells) of the Markdown table whose header line starts with ``header``."""
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith(header)), None)
    if start is None:
        return []
    rows: list[list[str]] = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append(_cells(line))
    return rows


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]
