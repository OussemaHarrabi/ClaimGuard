"""Unit checks of the evaluation report renderer.

These run without the mentor pack: the context is synthetic but shaped exactly like the one
``build_context`` produces, so the sections, the metrics tables and the honesty statements are
all exercised on numbers whose expected rendering is known here.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from scripts import edu_report

CLAIMS: tuple[str, ...] = tuple(f"C-{index:02d}" for index in range(1, 11))
RULES: tuple[str, ...] = ("R001", "R002", "R003")

#: Expected statuses per rule, in ``CLAIMS`` order.
EXPECTED: dict[str, tuple[str, ...]] = {
    "R001": ("FAIL", "FAIL", "FAIL", "FAIL", "PASS", "PASS", "PASS", "PASS", "PASS", "PASS"),
    "R002": (
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "UNABLE_TO_ASSESS",
        "UNABLE_TO_ASSESS",
    ),
    "R003": ("NOT_APPLICABLE",) * 10,
}

#: Predicted statuses: R001 adds one false alarm, R002 turns one PASS into an abstention and
#: misses both expected abstentions, R003 is exact.
PREDICTED: dict[str, tuple[str, ...]] = {
    "R001": ("FAIL", "FAIL", "FAIL", "FAIL", "FAIL", "PASS", "PASS", "PASS", "PASS", "PASS"),
    "R002": (
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "UNABLE_TO_ASSESS",
        "PASS",
        "PASS",
    ),
    "R003": ("NOT_APPLICABLE",) * 10,
}

OVERALL: dict[str, Any] = {
    "count": 30,
    "tp": 4,
    "fp": 1,
    "fn": 0,
    "tn": 25,
    "issue_precision": 0.8,
    "issue_recall": 1.0,
    "issue_f1": 8 / 9,
    "false_alarm_rate": 1 / 26,
    "status_accuracy": 26 / 30,
    "not_implemented": 0,
    "false_abstentions": 1,
    "missed_abstentions": 2,
}

BY_RULE: dict[str, dict[str, Any]] = {
    "R001": {
        "count": 10,
        "tp": 4,
        "fp": 1,
        "fn": 0,
        "tn": 5,
        "issue_precision": 0.8,
        "issue_recall": 1.0,
        "issue_f1": 8 / 9,
        "false_alarm_rate": 1 / 6,
        "status_accuracy": 0.9,
        "not_implemented": 0,
        "false_abstentions": 0,
        "missed_abstentions": 0,
    },
    "R002": {
        "count": 10,
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "tn": 10,
        "issue_precision": None,
        "issue_recall": None,
        "issue_f1": None,
        "false_alarm_rate": 0.0,
        "status_accuracy": 0.8,
        "not_implemented": 0,
        "false_abstentions": 1,
        "missed_abstentions": 2,
    },
    "R003": {
        "count": 10,
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "tn": 10,
        "issue_precision": None,
        "issue_recall": None,
        "issue_f1": None,
        "false_alarm_rate": 0.0,
        "status_accuracy": 1.0,
        "not_implemented": 0,
        "false_abstentions": 0,
        "missed_abstentions": 0,
    },
}

CONFUSION: tuple[dict[str, Any], ...] = (
    {"expected": "PASS", "predicted": "PASS", "count": 12},
    {"expected": "PASS", "predicted": "FAIL", "count": 1},
    {"expected": "PASS", "predicted": "UNABLE_TO_ASSESS", "count": 1},
    {"expected": "FAIL", "predicted": "FAIL", "count": 4},
    {"expected": "UNABLE_TO_ASSESS", "predicted": "PASS", "count": 2},
    {"expected": "NOT_APPLICABLE", "predicted": "NOT_APPLICABLE", "count": 10},
)


def _result_row(claim_id: str, rule_id: str, status: str) -> dict[str, Any]:
    """A contract-shaped gold row (only the fields the report reads are populated)."""
    return {"claim_id": claim_id, "rule_id": rule_id, "status": status}


def gold_rows() -> list[dict[str, Any]]:
    return [
        _result_row(claim_id, rule_id, EXPECTED[rule_id][index])
        for rule_id in RULES
        for index, claim_id in enumerate(CLAIMS)
    ]


def prediction_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rule_id in RULES:
        for index, claim_id in enumerate(CLAIMS):
            rows.append(
                {
                    **_result_row(claim_id, rule_id, PREDICTED[rule_id][index]),
                    "evidence": [{"path": "/invoice_number", "value": "INV-1"}],
                    "corrective_action": "Review the cited field.",
                }
            )
    return rows


def synthetic_metrics() -> dict[str, Any]:
    return {
        "overall": dict(OVERALL),
        "by_rule": {rule_id: dict(entry) for rule_id, entry in BY_RULE.items()},
        "confusion": [dict(item) for item in CONFUSION],
        "claims_with_all_statuses_correct": 6,
        "note": "Synthetic teaching benchmark only.",
    }


def synthetic_context() -> edu_report.ReportContext:
    """A context with the same shape ``build_context`` produces, built without the pack."""
    gold = gold_rows()
    mismatches = edu_report.collect_mismatches(gold, prediction_rows(), -1)
    return edu_report.ReportContext(
        split="development",
        generated_at="2026-01-01T00:00:00+00:00",
        command_line="--split development --output report.md",
        predictions=edu_report.FileIdentity(
            label="predictions",
            display="artifacts/report/development/predictions.jsonl",
            sha256="0" * 64,
            size_bytes=1234,
        ),
        predictions_source="produced by the engine CLI (`python -m claimguard.edu.run`)",
        scorer_command=("python", "evaluate.py", "--gold", "gold.jsonl"),
        scorer_exit_code=0,
        scorer_message="accepted",
        metrics_path="artifacts/report/development/metrics.json",
        context_path="artifacts/report/development/report_context.json",
        metrics=synthetic_metrics(),
        independent={
            "results": 30,
            "claims": 10,
            "evidence_pointers": 30,
            "problems": [],
            "ok": True,
        },
        audit={
            "pairs": 30,
            "implemented_pairs": 30,
            "implemented_accuracy": 26 / 30,
            "status_accuracy": 26 / 30,
            "not_implemented": 0,
            "tp": 4,
            "fp": 1,
            "fn": 0,
        },
        gate={"scope": "implemented", "min_accuracy": 1.0, "accuracy": 26 / 30, "passed": False},
        failure_reasons=("accuracy gate failed: implemented accuracy 0.866667 < 1",),
        supports=edu_report.support_analysis(gold, ()),
        mismatches=mismatches,
        mismatches_total=len(mismatches),
        category_counts=edu_report.category_counts(mismatches),
        claims=10,
        results=30,
    )


# ---------------------------------------------------------------------------------------
# Section and statement contract
# ---------------------------------------------------------------------------------------


def test_report_contains_every_required_section() -> None:
    rendered = edu_report.render_report(synthetic_context())
    missing = [section for section in edu_report.REQUIRED_SECTIONS if section not in rendered]
    assert missing == []


def test_report_states_every_honesty_rule_verbatim() -> None:
    context = synthetic_context()
    rendered = edu_report.render_report(context)
    statements = edu_report.honesty_statements(context)
    assert len(statements) == len(edu_report.HONESTY_STATEMENTS)
    for label, text in statements:
        assert f"**{label}.**" in rendered
        assert text in rendered
    assert "This report covers the development split" in rendered


def test_honesty_statements_name_the_split_counts_and_edges() -> None:
    context = synthetic_context()
    rendered = dict(edu_report.honesty_statements(context))
    split_text = rendered["Dataset split"]
    assert "development split (10 claims, 30 claim-rule pairs)" in split_text
    assert "200 held-out" in split_text
    edges = rendered["Labels cannot discriminate every edge"]
    for edge in edu_report.UNDISCRIMINATED_EDGES:
        assert edge in edges


def test_render_refuses_a_context_without_metrics() -> None:
    with pytest.raises(edu_report.ReportError):
        edu_report.render_report(edu_report.ReportContext(split="development"))
    with pytest.raises(edu_report.ReportError):
        edu_report.render_report(edu_report.ReportContext(metrics=synthetic_metrics()))


# ---------------------------------------------------------------------------------------
# Metrics rendering
# ---------------------------------------------------------------------------------------


def test_headline_metric_table_matches_the_metrics_payload() -> None:
    context = synthetic_context()
    rendered = edu_report.render_report(context)
    rows = _table_rows(rendered, "| Metric | Value |")
    values = {cells[0]: cells[1] for cells in rows}

    assert values["Claim-rule pairs scored"] == edu_report.fmt_int(OVERALL["count"])
    assert values["True positives (expected FAIL, predicted FAIL)"] == edu_report.fmt_int(
        OVERALL["tp"]
    )
    assert values["False positives"] == edu_report.fmt_int(OVERALL["fp"])
    assert values["False negatives"] == edu_report.fmt_int(OVERALL["fn"])
    assert values["True negatives (neither side FAIL)"] == edu_report.fmt_int(OVERALL["tn"])
    assert values["Issue precision"] == edu_report.fmt_ratio(OVERALL["issue_precision"])
    assert values["Issue recall"] == edu_report.fmt_ratio(OVERALL["issue_recall"])
    assert values["Issue F1"] == edu_report.fmt_ratio(OVERALL["issue_f1"])
    assert values["False-alarm rate"] == edu_report.fmt_ratio(OVERALL["false_alarm_rate"])
    assert values["Status accuracy"] == edu_report.fmt_ratio(OVERALL["status_accuracy"])
    assert values["False abstentions"] == edu_report.fmt_int(OVERALL["false_abstentions"])
    assert values["Missed abstentions"] == edu_report.fmt_int(OVERALL["missed_abstentions"])
    assert values["NOT_IMPLEMENTED predictions"] == edu_report.fmt_int(OVERALL["not_implemented"])
    assert values["Claim exact match"] == "6 / 10 = 0.6000"


def test_per_rule_table_matches_the_metrics_payload() -> None:
    context = synthetic_context()
    rendered = edu_report.render_report(context)
    rows = _table_rows(rendered, "| Rule | n | Expected FAIL |")
    assert [cells[0] for cells in rows] == list(RULES)
    for cells in rows:
        rule_id = cells[0]
        entry = BY_RULE[rule_id]
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


def test_undefined_precision_is_null_never_one_hundred_percent() -> None:
    context = synthetic_context()
    rendered = edu_report.render_report(context)
    rows = {cells[0]: cells for cells in _table_rows(rendered, "| Rule | n | Expected FAIL |")}
    assert rows["R002"][7] == "null"
    assert rows["R002"][8] == "null"
    assert rows["R002"][9] == "null"
    assert edu_report.fmt_ratio(None) == "null"
    assert "never as 100%" in rendered


def test_confusion_table_matches_the_confusion_list() -> None:
    context = synthetic_context()
    rendered = edu_report.render_report(context)
    rows = _table_rows(rendered, "| Expected \\ Predicted |")
    header = _table_header(rendered, "| Expected \\ Predicted |")
    assert header[1:] == list(edu_report.STATUS_ORDER)
    observed = {cells[0]: cells[1:] for cells in rows}
    for item in CONFUSION:
        expected = str(item["expected"])
        predicted = str(item["predicted"])
        column = header.index(predicted) - 1
        assert observed[expected][column] == str(item["count"])
    assert sum(int(cell) for cells in observed.values() for cell in cells) == OVERALL["count"]


def test_uncertainty_handling_is_reported_separately_from_issue_detection() -> None:
    rendered = edu_report.render_report(synthetic_context())
    assert "### Issue detection" in rendered
    assert "### Uncertainty handling" in rendered
    uncertainty = rendered.split("### Uncertainty handling")[1].split("###")[0]
    assert "False abstentions: 1" in uncertainty
    assert "missed abstentions: 2" in uncertainty
    detection = rendered.split("### Issue detection")[1].split("###")[0]
    assert "False alarms: 1" in detection
    assert "Missed issues: 0" in detection


# ---------------------------------------------------------------------------------------
# Error categories, support and the ablation
# ---------------------------------------------------------------------------------------


def test_category_counts_reproduce_the_metrics_payload() -> None:
    context = synthetic_context()
    assert context.category_counts == {
        "false_alarm": 1,
        "missed_issue": 0,
        "false_abstention": 1,
        "missed_abstention": 2,
        "other_status_disagreement": 0,
    }
    problems = edu_report.cross_check_categories(context.category_counts, OVERALL)
    assert problems == []
    wrong = edu_report.cross_check_categories({"false_alarm": 0}, OVERALL)
    assert any("false_alarm" in problem for problem in wrong)


def test_a_pair_may_belong_to_two_categories() -> None:
    assert edu_report.mismatch_categories("FAIL", "UNABLE_TO_ASSESS") == (
        "missed_issue",
        "false_abstention",
    )
    assert edu_report.mismatch_categories("PASS", "FAIL") == ("false_alarm",)
    assert edu_report.mismatch_categories("PASS", "NOT_IMPLEMENTED") == (
        "other_status_disagreement",
    )
    assert edu_report.mismatch_categories("NOT_APPLICABLE", "PASS") == (
        "other_status_disagreement",
    )
    assert edu_report.mismatch_categories("UNABLE_TO_ASSESS", "UNABLE_TO_ASSESS") == ()


def test_mismatches_are_enumerated_with_claim_rule_and_evidence() -> None:
    context = synthetic_context()
    mismatches = context.mismatches
    assert context.mismatches_total == 4
    assert len(mismatches) == 4
    first = mismatches[0]
    assert first.rule_id == "R001"
    assert first.claim_id == "C-05"
    assert (first.expected, first.predicted) == ("PASS", "FAIL")
    assert first.evidence == (("/invoice_number", '"INV-1"'),)
    rendered = edu_report.render_report(context)
    row = next(line for line in rendered.splitlines() if line.startswith("| C-05 |"))
    assert row.startswith("| C-05 | R001 | PASS | FAIL | false_alarm |")
    assert '`/invoice_number` = `"INV-1"`' in row
    assert "Review the cited field." in row
    assert len([line for line in rendered.splitlines() if line.startswith("| C-")]) == 4


def test_error_analysis_says_so_when_there_are_no_findings_to_report() -> None:
    context = synthetic_context()
    clean = edu_report.ReportContext(
        split=context.split,
        generated_at=context.generated_at,
        metrics={
            **synthetic_metrics(),
            "overall": {
                **OVERALL,
                "tp": 5,
                "fp": 0,
                "fn": 0,
                "false_abstentions": 0,
                "missed_abstentions": 0,
                "status_accuracy": 1.0,
            },
            "claims_with_all_statuses_correct": 10,
        },
        supports=context.supports,
        claims=10,
        results=30,
    )
    rendered = edu_report.render_report(clean)
    assert "no false alarms and no missed issues" in rendered
    assert "We do not manufacture them" in rendered
    assert "cannot be satisfied from this run" in rendered


def test_thinnest_support_is_named_and_ranked() -> None:
    context = synthetic_context()
    rendered = edu_report.render_report(context)
    assert [item.rule_id for item in context.supports] == ["R002", "R003", "R001"]
    assert "Thinnest positive support" in rendered
    assert "**R003** (0 expected FAIL of 10 pair(s))" in rendered
    assert "**R001** (4 expected FAIL of 10 pair(s))" in rendered
    assert "| R001 | 6 | 4 | 0 | 0 | 4 | 25.00 pts |" in rendered  # R001: one flip = 1/4
    assert "| R002 | 8 | 0 | 2 | 0 | 2 | recall undefined |" in rendered
    assert "recall undefined" in rendered
    assert "Rules with no expected FAIL at all" in rendered
    assert "R002, R003" in rendered


def test_ablation_section_says_it_was_not_computed_when_absent() -> None:
    rendered = edu_report.render_report(synthetic_context())
    assert "### Reference ablation: the pack's own baseline" in rendered
    assert "Not computed in this run (`--no-baseline` was given)" in rendered
    assert "Nothing is estimated" in rendered


def test_ablation_section_reports_a_failed_ablation_without_refusing() -> None:
    context = replace(synthetic_context(), baseline_error="the pack baseline could not run")
    rendered = edu_report.render_report(context)
    assert (
        "The ablation was requested but did not run: the pack baseline could not run." in rendered
    )
    assert "**Verdict: NON-CONFORMANT**" in rendered  # a gate failure, not an ablation failure


def test_ablation_renders_the_baseline_comparison() -> None:
    context = synthetic_context()
    baseline = edu_report.BaselineSummary(
        command=("python", "run_baseline.py"),
        stdout="Processed 10 claims. Implemented: R001, R003, R006.",
        predictions=edu_report.FileIdentity(
            label="baseline predictions",
            display="artifacts/report/development/baseline_predictions.jsonl",
            sha256="1" * 64,
            size_bytes=999,
        ),
        scorer_exit_code=0,
        metrics={
            "overall": {**OVERALL, "tp": 4, "fn": 1, "status_accuracy": 0.2, "not_implemented": 6},
            "claims_with_all_statuses_correct": 0,
        },
        mismatches=(),
        failure_reasons=(),
    )
    context = replace(context, baseline=baseline)
    rendered = edu_report.render_report(context)
    rows = {
        cells[0]: cells
        for cells in _table_rows(rendered, "| Metric | Our engine | Pack baseline |")
    }
    assert rows["Claim exact match"][1] == "6 / 10"
    assert rows["Claim exact match"][2] == "0 / 10"
    assert rows["Status accuracy"][1] == "0.8667"
    assert rows["Status accuracy"][2] == "0.2000"
    assert "Processed 10 claims. Implemented: R001, R003, R006." in rendered


# ---------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------


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


def _table_header(text: str, header: str) -> list[str]:
    line = next((item for item in text.splitlines() if item.startswith(header)), "")
    return _cells(line)


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]
