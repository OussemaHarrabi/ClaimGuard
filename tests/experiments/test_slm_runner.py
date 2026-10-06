"""Exercise reporting without a GPU, including partial-run and shared-output pitfalls."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from claimguard.benchmark.corpus import generate_cases
from claimguard.benchmark.scoring import score_output
from claimguard.edu.explain.fallback import build_explanation
from claimguard.edu.policy import RuleContext

ROOT = Path(__file__).parents[2]


def _cases() -> list[dict[str, Any]]:
    context = RuleContext.from_rules_dir(ROOT / "tests/edu/fixtures/pack_reference")
    return generate_cases(context, variants=1)[:2]


def _record(case: dict[str, Any]) -> dict[str, Any]:
    output = build_explanation(case["finding"], case["rule"])
    return {
        "case_id": case["case_id"],
        "candidate": output,
        "raw": [json.dumps(output)],
        "fallback_used": False,
        "measurements": [],
    }


def _report(
    folder: Path,
    *,
    reviews: Path | None = None,
    models: tuple[str, ...] = ("gemma4-e4b", "smollm3-3b"),
) -> None:
    command = [
        sys.executable,
        "-m",
        "notebooks.slm_benchmark_runner",
        "report",
        "--output",
        str(folder),
        "--models",
        *models,
    ]
    if reviews:
        command.extend(["--reviews", str(reviews)])
    subprocess.run(  # noqa: S603 - fixed Python module, no shell
        command, cwd=ROOT, capture_output=True, text=True, check=True, timeout=30
    )


def test_identical_outputs_across_configs_can_receive_separate_review_pairs(tmp_path: Path) -> None:
    case = _cases()[0]
    record = _record(case)
    (tmp_path / "cases.json").write_text(json.dumps([case]), encoding="utf-8")
    key = score_output(case, record["candidate"], [], raw_text=record["raw"][0])["review_key"]
    labels: list[dict[str, Any]] = []
    for config in ("gemma4-e4b-nf4", "smollm3-3b-nf4"):
        folder = tmp_path / config
        folder.mkdir()
        (folder / "explanations.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        for reviewer in ("a", "b"):
            labels.append(
                {
                    "config": config,
                    "review_key": key,
                    "reviewer": reviewer,
                    "unsupported": False,
                    "correction_safe": True,
                    "clarity": 5,
                    "usefulness": 5,
                }
            )
    path = tmp_path / "reviews.json"
    path.write_text(json.dumps(labels), encoding="utf-8")
    _report(tmp_path, reviews=path)
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert all(row["reviewed"] == 1 for row in summary["configurations"].values())


def test_resumed_report_adds_missing_review_rows_without_erasing_labels(tmp_path: Path) -> None:
    cases = _cases()
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    folder = tmp_path / "gemma4-e4b-nf4"
    folder.mkdir()
    records = [_record(case) for case in cases]
    path = folder / "explanations.jsonl"
    path.write_text(json.dumps(records[0]) + "\n", encoding="utf-8")
    _report(tmp_path)
    template = tmp_path / "semantic-review-template.csv"
    with template.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["notes"] = "Keep my annotation"
    with template.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    _report(tmp_path)
    with template.open(encoding="utf-8", newline="") as stream:
        updated = list(csv.DictReader(stream))
    assert len(updated) == 4
    assert updated[0]["notes"] == "Keep my annotation"
    assert all(row["raw_text"] for row in updated)


def test_finalist_report_keeps_other_models_and_real_reviewer_names(tmp_path: Path) -> None:
    case = _cases()[0]
    (tmp_path / "cases.json").write_text(json.dumps([case]), encoding="utf-8")
    for config in ("gemma4-e4b-nf4", "smollm3-3b-nf4"):
        folder = tmp_path / config
        folder.mkdir()
        (folder / "explanations.jsonl").write_text(
            json.dumps(_record(case)) + "\n", encoding="utf-8"
        )
    _report(tmp_path)
    template = tmp_path / "semantic-review-template.csv"
    with template.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["reviewer"] = "Eya"
    rows[0]["notes"] = "Preserve named reviewer"
    rows[-1]["notes"] = "Preserve other model"
    with template.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _report(tmp_path, models=("gemma4-e4b",))
    with template.open(encoding="utf-8", newline="") as stream:
        updated = list(csv.DictReader(stream))
    assert len(updated) == 4
    assert updated[0]["reviewer"] == "Eya"
    assert updated[0]["notes"] == "Preserve named reviewer"
    assert updated[-1]["notes"] == "Preserve other model"
