"""Delivered synthetic data must be scored by our engine, never a mock."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from claimguard.benchmark.corpus import generate_cases
from claimguard.benchmark.starter import starter_cases, stratified_cases
from claimguard.edu.policy import RuleContext
from tests.edu import RULES_DIR


def test_small_screen_budget_still_covers_all_rules_and_statuses() -> None:
    from notebooks.slm_benchmark_runner import cases_for, parser

    cases = cases_for(parser().parse_args(["prepare", "--limit", "60"]))
    assert {case["finding"]["rule_id"] for case in cases} == {
        f"R{index:03}" for index in range(1, 16)
    }
    assert {case["finding"]["status"] for case in cases} == {
        "PASS",
        "FAIL",
        "UNABLE_TO_ASSESS",
        "NOT_APPLICABLE",
    }


def test_sampled_starter_report_does_not_claim_unlimited_run(tmp_path: Path) -> None:
    from argparse import Namespace

    from notebooks.slm_benchmark_runner import report

    case = generate_cases(RuleContext.from_rules_dir(RULES_DIR), variants=1)[0]
    (tmp_path / "cases.json").write_text(json.dumps([case]))
    (tmp_path / "manifest.json").write_text(json.dumps({"limit": 0, "per_stratum": 2}))
    report(Namespace(output=tmp_path, reviews=None, models=["gemma4-e4b"], precisions=["nf4"]))
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["configurations"]["gemma4-e4b-nf4"]["gates"]["unlimited_run"] is False


def test_stratification_covers_every_available_rule_status_before_repeating() -> None:
    cases = generate_cases(RuleContext.from_rules_dir(RULES_DIR), variants=1)
    selected = stratified_cases(cases, per_stratum=1)

    def key(case: dict[str, Any]) -> tuple[str, str]:
        return case["finding"]["rule_id"], case["finding"]["status"]

    assert {key(case) for case in selected} == {key(case) for case in cases}
    assert len(selected) == len({key(case) for case in cases})
    assert stratified_cases(cases, per_stratum=0) == cases


def test_pack_gold_is_checked_but_not_used_to_construct_model_finding(tmp_path: Path) -> None:
    source = generate_cases(RuleContext.from_rules_dir(RULES_DIR), variants=1)[:15]
    folder = tmp_path / "data" / "validation"
    folder.mkdir(parents=True)
    claims = [source[0]["envelope"]]
    gold = [case["finding"] for case in source]
    (folder / "claims.jsonl").write_text(json.dumps(claims[0]) + "\n")
    (folder / "expected_results.jsonl").write_text(
        "\n".join(json.dumps(row) for row in gold) + "\n"
    )
    cases = starter_cases(tmp_path, "validation", RuleContext.from_rules_dir(RULES_DIR))
    assert len(cases) == 15
    assert cases[0]["finding"] == source[0]["finding"]
    assert all(case["source_split"] == "validation" for case in cases)
    # Valid evidence may differ from the organizer's chosen pointer subset.
    alternate = deepcopy(gold)
    alternate[0]["evidence"] = [{"path": "/currency", "value": claims[0]["currency"]}]
    (folder / "expected_results.jsonl").write_text(
        "\n".join(json.dumps(row) for row in alternate) + "\n"
    )
    assert len(starter_cases(tmp_path, "validation", RuleContext.from_rules_dir(RULES_DIR))) == 15
    alternate[0]["evidence"][0]["value"] = "FORGED"
    (folder / "expected_results.jsonl").write_text(
        "\n".join(json.dumps(row) for row in alternate) + "\n"
    )
    with pytest.raises(ValueError, match="Evidence integrity"):
        starter_cases(tmp_path, "validation", RuleContext.from_rules_dir(RULES_DIR))
    broken = deepcopy(gold)
    broken[0]["status"] = "FAIL"
    (folder / "expected_results.jsonl").write_text(
        "\n".join(json.dumps(row) for row in broken) + "\n"
    )
    with pytest.raises(ValueError, match="Gold disagreement"):
        starter_cases(tmp_path, "validation", RuleContext.from_rules_dir(RULES_DIR))


def test_pack_missing_gold_pair_is_not_silently_accepted(tmp_path: Path) -> None:
    source = generate_cases(RuleContext.from_rules_dir(RULES_DIR), variants=1)[:15]
    folder = tmp_path / "data" / "stress"
    folder.mkdir(parents=True)
    (folder / "claims.jsonl").write_text(json.dumps(source[0]["envelope"]) + "\n")
    (folder / "expected_results.jsonl").write_text(
        "\n".join(json.dumps(case["finding"]) for case in source[1:]) + "\n"
    )
    with pytest.raises(ValueError, match="Gold coverage"):
        starter_cases(tmp_path, "stress", RuleContext.from_rules_dir(RULES_DIR))
