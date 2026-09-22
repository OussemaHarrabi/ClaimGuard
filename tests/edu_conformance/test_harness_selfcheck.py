"""Self-checks for the mentor-pack conformance harness.

The harness is only trustworthy if it (a) accepts the pack's own baseline predictions, which
the mentor's strict scorer must accept, and (b) fails loudly on predictions that the scorer
rejects *or* that break the frozen contract in ways the scorer does not check.

Baseline fixture: ``python <pack>/src/run_baseline.py --input
<pack>/data/development/claims.jsonl --output C:/tmp/packout/baseline_dev.jsonl``
(override the location with ``CLAIMGUARD_BASELINE_DIR``). It is regenerated when missing or
when it does not hold the expected 400 claims x 15 rules = 6000 results.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts.edu_conformance import (
    RULE_IDS,
    PointerError,
    PredictionAudit,
    as_mapping,
    cross_check_metrics,
    independent_check,
    json_equal,
    resolve_pointer,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_ROOT = REPO_ROOT / "ClaimGuardAI_Student_Starter_Pack" / "ClaimGuardAI_Student_Starter_Pack"
HARNESS = REPO_ROOT / "scripts" / "edu_conformance.py"
BASELINE_DIR = Path(os.environ.get("CLAIMGUARD_BASELINE_DIR", "C:/tmp/packout"))
BASELINE = BASELINE_DIR / "baseline_dev.jsonl"
DEV_CLAIMS = PACK_ROOT / "data" / "development" / "claims.jsonl"
EXPECTED_DEV_RESULTS = 400 * 15

#: These self-checks exercise the mentor's own scorer and gold labels, which ship
#: in the delivered pack and are not tracked in git. They therefore run locally
#: (``make edu-conformance``) and as a pre-submission gate, not in CI. The
#: pointer/equality primitives below stay unguarded so CI still covers them.
requires_pack = pytest.mark.skipif(
    not (PACK_ROOT / "src" / "evaluate.py").is_file(),
    reason="mentor starter pack absent (delivered reference material, not tracked in git)",
)


def _mutated_baseline(lines: list[str], destination: Path, mutate: Any) -> Path:
    """Write a copy of the baseline lines with one JSON object remapped."""
    rows = [json.loads(line) for line in lines]
    mutate(rows)
    destination.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )
    return destination


@pytest.fixture(scope="session")
def baseline_lines() -> list[str]:
    """The pack's own baseline predictions for the development split."""
    lines: list[str] = []
    if BASELINE.is_file():
        lines = [line for line in BASELINE.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != EXPECTED_DEV_RESULTS:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
            [
                sys.executable,
                str(PACK_ROOT / "src" / "run_baseline.py"),
                "--input",
                str(DEV_CLAIMS),
                "--output",
                str(BASELINE),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        lines = [line for line in BASELINE.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == EXPECTED_DEV_RESULTS
    return lines


def run_harness(
    pred: Path, workdir: Path, *extra: str, split: str | None = "development"
) -> subprocess.CompletedProcess[str]:
    """Invoke the harness CLI exactly as an operator would."""
    selectors = ["--split", split] if split is not None else []
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        [
            sys.executable,
            str(HARNESS),
            "--pred",
            str(pred),
            *selectors,
            "--workdir",
            str(workdir),
            *extra,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def load_report(workdir: Path, split: str = "development") -> dict[str, Any]:
    payload: Any = json.loads((workdir / split / "conformance.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return as_mapping(payload)


# ---------------------------------------------------------------------------------------
# The accepted baseline
# ---------------------------------------------------------------------------------------


@requires_pack
def test_harness_accepts_the_pack_baseline(baseline_lines: list[str], tmp_path: Path) -> None:
    completed = run_harness(BASELINE, tmp_path)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "RESULT: CONFORMANT" in completed.stdout
    assert "per-rule" in completed.stdout
    assert "confusion (expected -> predicted)" in completed.stdout

    report = load_report(tmp_path)
    assert report["conformant"] is True
    assert report["failure_reasons"] == []
    assert report["scorer"]["exit_code"] == 0

    overall = report["metrics"]["overall"]
    assert overall["count"] == EXPECTED_DEV_RESULTS
    assert overall["status_accuracy"] == 0.2
    assert overall["not_implemented"] == 4800
    assert report["metrics"]["claims_with_all_statuses_correct"] == 0
    assert len(report["metrics"]["by_rule"]) == 15
    assert report["metrics"]["confusion"]

    independent = report["independent"]
    assert independent["ok"] is True
    assert independent["problems"] == []
    assert independent["results"] == EXPECTED_DEV_RESULTS
    assert independent["claims"] == 400
    assert independent["evidence_pointers"] > 0

    audit = report["independent_audit"]
    assert audit["status_accuracy"] == 0.2
    assert audit["implemented_pairs"] == 1200  # R001, R003, R006 only
    assert audit["implemented_accuracy"] == 1.0
    assert report["gate"]["passed"] is True


# ---------------------------------------------------------------------------------------
# Failures the mentor's scorer already rejects
# ---------------------------------------------------------------------------------------


@requires_pack
def test_fabricated_evidence_value_is_rejected(baseline_lines: list[str], tmp_path: Path) -> None:
    def fabricate(rows: list[dict[str, Any]]) -> None:
        rows[0]["evidence"][0]["value"] = "INVENTED"

    pred = _mutated_baseline(baseline_lines, tmp_path / "fabricated.jsonl", fabricate)
    completed = run_harness(pred, tmp_path)

    assert completed.returncode != 0
    assert "RESULT: NON-CONFORMANT" in completed.stdout
    # The oracle's own rejection is surfaced verbatim...
    assert "Evaluation rejected" in completed.stdout
    assert "Evidence value mismatch" in completed.stdout
    # ...and the independent check names the pointer and both values.
    assert "evidence value mismatch at /invoice_number" in completed.stdout
    report = load_report(tmp_path)
    assert report["scorer"]["exit_code"] == 2
    assert any("independent admissibility" in reason for reason in report["failure_reasons"])


@requires_pack
def test_missing_claim_rule_pair_is_rejected(baseline_lines: list[str], tmp_path: Path) -> None:
    pred = tmp_path / "missing_pair.jsonl"
    pred.write_text("\n".join(baseline_lines[:-1]) + "\n", encoding="utf-8")
    completed = run_harness(pred, tmp_path)

    assert completed.returncode != 0
    assert "Prediction coverage mismatch" in completed.stdout
    assert "missing results for ['R015']" in completed.stdout
    report = load_report(tmp_path)
    assert report["scorer"]["exit_code"] == 2
    assert report["independent"]["results"] == EXPECTED_DEV_RESULTS - 1


# ---------------------------------------------------------------------------------------
# Failures the mentor's scorer does NOT reject: the second opinion has to catch them
# ---------------------------------------------------------------------------------------


@requires_pack
def test_independent_check_catches_a_contract_break_the_oracle_ignores(
    baseline_lines: list[str], tmp_path: Path
) -> None:
    def mislabel_method(rows: list[dict[str, Any]]) -> None:
        rows[0]["method"] = "model_assisted"

    pred = _mutated_baseline(baseline_lines, tmp_path / "bad_method.jsonl", mislabel_method)
    completed = run_harness(pred, tmp_path)

    assert completed.returncode != 0, completed.stdout
    report = load_report(tmp_path)
    assert report["scorer"]["exit_code"] == 0  # the oracle accepted these predictions
    assert report["conformant"] is False
    assert any(
        "method must be 'deterministic'" in problem for problem in report["independent"]["problems"]
    )


# ---------------------------------------------------------------------------------------
# The accuracy gate
# ---------------------------------------------------------------------------------------


@requires_pack
def test_accuracy_gate_is_configurable(baseline_lines: list[str], tmp_path: Path) -> None:
    strict = run_harness(BASELINE, tmp_path / "strict", "--accuracy-scope", "total")
    assert strict.returncode != 0
    assert "accuracy gate failed: total accuracy 0.200000" in strict.stdout

    lenient = run_harness(
        BASELINE, tmp_path / "lenient", "--accuracy-scope", "total", "--min-accuracy", "0.2"
    )
    assert lenient.returncode == 0, lenient.stdout + lenient.stderr
    assert "RESULT: CONFORMANT" in lenient.stdout

    disabled = run_harness(BASELINE, tmp_path / "disabled", "--min-accuracy", "-1")
    assert disabled.returncode == 0, disabled.stdout + disabled.stderr


@requires_pack
def test_all_requires_one_predictions_file_per_split(tmp_path: Path) -> None:
    completed = run_harness(BASELINE, tmp_path, "--all", split=None)
    assert completed.returncode == 2
    assert "{split}" in completed.stdout


# ---------------------------------------------------------------------------------------
# Unit-level checks of the independent primitives
# ---------------------------------------------------------------------------------------


def test_pointer_resolution_and_escapes() -> None:
    document = {"a": {"b": [10, {"c~d": "x/y"}]}, "": 7}
    assert resolve_pointer(document, "") is document
    assert resolve_pointer(document, "/a/b/0") == 10
    assert resolve_pointer(document, "/a/b/1/c~0d") == "x/y"
    assert resolve_pointer(document, "/") == 7
    assert resolve_pointer({"v": None}, "/v") is None


def test_pointer_failures_are_explicit() -> None:
    with pytest.raises(PointerError):
        resolve_pointer({"a": 1}, "a")
    with pytest.raises(PointerError):
        resolve_pointer({"a": 1}, "/missing")
    with pytest.raises(PointerError):
        resolve_pointer({"a": [1]}, "/a/3")
    with pytest.raises(PointerError):
        resolve_pointer({"a": [1]}, "/a/x")
    with pytest.raises(PointerError):
        resolve_pointer({"a": 1}, "/a/b")


def test_json_equality_is_type_exact() -> None:
    assert json_equal(True, True)
    assert not json_equal(True, 1)
    assert not json_equal(1, True)
    assert json_equal(1, 1.0)
    assert not json_equal("1", 1)
    assert json_equal({"a": [1, {"b": None}]}, {"a": [1.0, {"b": None}]})
    assert not json_equal({"a": 1}, {"a": 1, "b": 2})
    assert not json_equal([1, 2], [2, 1])


@requires_pack
def test_independent_check_flags_contract_violations_on_real_pack_data() -> None:
    claim: dict[str, Any] = json.loads(DEV_CLAIMS.read_text(encoding="utf-8").splitlines()[0])
    line_ids = [line["line_id"] for line in claim["lines"]]

    def result(rule_id: str) -> dict[str, Any]:
        return {
            "claim_id": claim["claim_id"],
            "rule_id": rule_id,
            "rule_version": "1.0.0",
            "status": "PASS",
            "severity": "high",
            "affected_line_ids": line_ids,
            "evidence": [{"path": "/invoice_number", "value": claim["invoice_number"]}],
            "rule_source": f"fictional-rulebook/{rule_id}@1.0.0",
            "explanation": "Contract-shaped.",
            "corrective_action": "",
            "confidence": None,
            "confidence_kind": "not_probabilistic",
            "requires_human_review": False,
            "method": "deterministic",
            "review_status": "unreviewed",
        }

    clean: list[dict[str, Any]] = [result(rule_id) for rule_id in RULE_IDS]
    accepted = independent_check(clean, [claim])
    assert accepted.ok is True, accepted.problems
    assert accepted.evidence_pointers == len(RULE_IDS)

    fabricated = json.loads(json.dumps(clean))
    fabricated[0]["evidence"][0]["value"] = "INVENTED"
    assert "evidence value mismatch at /invoice_number" in " ".join(
        independent_check(fabricated, [claim]).problems
    )

    unknown_line = json.loads(json.dumps(clean))
    unknown_line[0]["affected_line_ids"] = ["L-DOES-NOT-EXIST"]
    assert "absent from the claim" in " ".join(independent_check(unknown_line, [claim]).problems)

    incomplete = [result(rule_id) for rule_id in RULE_IDS[:-1]]
    assert "missing results for ['R015']" in " ".join(
        independent_check(incomplete, [claim]).problems
    )

    extra_key = json.loads(json.dumps(clean))
    extra_key[0]["severity_note"] = "oops"
    assert "exact 15-key set" in " ".join(independent_check(extra_key, [claim]).problems)

    not_implemented = json.loads(json.dumps(clean))
    not_implemented[0]["status"] = "NOT_IMPLEMENTED"
    not_implemented[0]["evidence"] = []
    assert independent_check(not_implemented, [claim]).ok is True


@requires_pack
def test_stale_oracle_metrics_are_caught_by_the_cross_check() -> None:
    problems: list[str] = []
    metrics: dict[str, Any] = {
        "overall": {
            "count": 6000,
            "tp": 0,
            "fp": 0,
            "fn": 231,
            "status_accuracy": 0.9,
            "not_implemented": 4800,
        }
    }
    cross_check_metrics(
        metrics,
        PredictionAudit(
            pairs=6000,
            implemented_pairs=1200,
            implemented_accuracy=1.0,
            status_accuracy=0.2,
            not_implemented=4800,
            tp=88,
            fp=0,
            fn=231,
        ),
        problems,
    )
    assert any("status_accuracy" in problem and "disagrees" in problem for problem in problems)
    assert any("'tp'" in problem for problem in problems)
