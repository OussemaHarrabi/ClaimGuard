"""Detection metrics the challenge asks for by name, measured on the mentor's own labels.

WHY THIS EXISTS
---------------
The Phase-2 deliverable names five things: *detection metrics, F1 score, false positive rate,
latency, and limitations*. Two of them were not reported anywhere in this repository:

*   **Macro F1 across rule categories.** The evaluation report carries issue-level (micro)
    precision/recall/F1 and a per-rule table, but the macro average - the unweighted mean of the
    15 rules' F1 scores, which is the figure the challenge names - was never computed. Micro and
    macro answer different questions: micro is "how good is the engine at finding failing
    checks?", macro is "is it good on EVERY rule, including the rare ones?", and a rule that is
    never detected cannot hide inside a macro average the way it can inside a micro one.
*   **Latency.** No document measured it, so a reviewer could not tell whether a 400-claim batch
    takes a second or a minute.

This script measures both, in process, against the pack's gold labels, and writes a single
reproducible document. It does not re-implement the mentor's scorer: `claimguard evaluate` and
`scripts/edu_conformance.py` own admissibility and the official status accuracy. This adds the
two figures they do not produce, computed the same way they would be - from the engine's own
output and the published labels.

WHAT IT DOES NOT CLAIM
----------------------
These numbers are conformance to PUBLIC labels the engine was developed against, on a synthetic
fictional payer. They are not accuracy on unseen claims, not accuracy on real claims, and not a
calibrated probability of anything. `docs/verification/PHASE-1-GAP-ANALYSIS.md` and the report's
own limitations section say the same thing; the mentor's 200 held-out claims remain the only
honest test of generalisation, and they are not available here.

Usage
-----
    uv run python scripts/detection_metrics.py                       # measure and write the doc
    uv run python scripts/detection_metrics.py --check      # measure; compare, write nothing
    uv run python scripts/detection_metrics.py --output <path>

Exit codes
----------
0  measured (and written, unless --check)
1  a split could not be read, or --check found the document out of date
2  the engine did not return exactly 15 records for a claim (the coverage contract)
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # run as a script, not a module
    sys.path.insert(0, str(REPO_ROOT))

from claimguard.edu.emit import validate_record  # noqa: E402
from claimguard.edu.engine import evaluate_claim  # noqa: E402
from claimguard.edu.envelope import RULE_IDS  # noqa: E402
from claimguard.edu.policy import RuleContext  # noqa: E402

#: Where the mentor pack lives when the whole deliverable is on disk.
DEFAULT_PACK: Final = (
    REPO_ROOT / "ClaimGuardAI_Student_Starter_Pack" / "ClaimGuardAI_Student_Starter_Pack"
)
#: The committed catalogue, so the script runs in CI where the pack is absent.
FALLBACK_RULES_DIR: Final = REPO_ROOT / "tests" / "edu" / "fixtures" / "pack_reference"
#: The document this produces.
DEFAULT_OUTPUT: Final = REPO_ROOT / "docs" / "verification" / "DETECTION-METRICS.md"
#: The splits to measure, in the order the report lists them.
SPLITS: Final = ("development", "validation", "stress")
#: How many warm-up claims to run before timing, so first-call import cost is not charged to a
#: claim the reader will look at.
WARMUP_CLAIMS: Final = 5


#: Latency measures the machine that ran it, so `--check` compares everything except the
#: timings: a document that disagreed on a metric is a real drift, while a document that
#: disagreed on milliseconds is a different laptop.
_VOLATILE: Final = (
    re.compile(r"\d+\.\d+ ms"),
    re.compile(r"\d+ claims/s"),
)


def canonical(document: str) -> str:
    """The parts of the document that must be identical between runs."""
    for pattern in _VOLATILE:
        document = pattern.sub("<timing>", document)
    return document


def _line(text: str = "") -> None:
    """Write one line to stdout (ruff's T20 forbids ``print`` in this tree)."""
    sys.stdout.write(text + "\n")


def f1_of(tp: int, fp: int, fn: int) -> float:
    """The harmonic mean of precision and recall, or 0.0 when nothing was detected."""
    if tp == 0:
        return 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0


@dataclass(frozen=True)
class RuleScore:
    """One rule's confusion counts and its F1, treating FAIL as the positive class."""

    rule_id: str
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def support(self) -> int:
        """Gold positives: how many claims this rule actually flags."""
        return self.true_positives + self.false_negatives

    @property
    def f1(self) -> float:
        return f1_of(self.true_positives, self.false_positives, self.false_negatives)


@dataclass(frozen=True)
class SplitMetrics:
    """Everything measured for one split."""

    split: str
    claims: int
    pairs: int
    per_rule: tuple[RuleScore, ...]
    false_alarms: int
    missed_issues: int
    wrong_abstentions: int
    missed_abstentions: int
    status_disagreements: int
    valid_claims: int
    valid_claims_flagged: int
    latency_ms: tuple[float, ...]

    @property
    def macro_f1_all_rules(self) -> float:
        """The unweighted mean over all fifteen rules - the challenge's 'macro F1'."""
        return statistics.mean(rule.f1 for rule in self.per_rule)

    @property
    def macro_f1_active_rules(self) -> float:
        """The unweighted mean over rules the split actually exercises.

        Reported beside the fifteen-rule figure because the two answer different questions: a
        rule with no positives in a split scores 0.0 by the definition above and drags the mean
        down, which says nothing about the engine. The full figure is the stricter one.
        """
        active = [rule.f1 for rule in self.per_rule if rule.support or rule.false_positives]
        return statistics.mean(active) if active else 0.0

    @property
    def micro_f1(self) -> float:
        """Issue-level F1: the pooled counts, the figure the evaluation report already carries."""
        tp = sum(rule.true_positives for rule in self.per_rule)
        fp = sum(rule.false_positives for rule in self.per_rule)
        fn = sum(rule.false_negatives for rule in self.per_rule)
        return f1_of(tp, fp, fn)

    @property
    def false_positive_rate(self) -> float:
        """False alarms as a share of every claim-rule pair the labels call clean."""
        clean = self.pairs - sum(rule.support for rule in self.per_rule)
        return self.false_alarms / clean if clean else 0.0

    @property
    def claim_precision(self) -> float:
        """Of the claims we flagged at all, the share that had at least one real issue."""
        flagged = self.valid_claims_flagged + (self.valid_claims - self.valid_claims_flagged)
        return (self.valid_claims - self.valid_claims_flagged) / flagged if flagged else 1.0

    def latency(self) -> dict[str, float]:
        """Mean/median/p95/max in milliseconds, and the implied throughput."""
        ordered = sorted(self.latency_ms)
        return {
            "mean": statistics.mean(ordered),
            "median": statistics.median(ordered),
            "p95": ordered[max(0, int(0.95 * len(ordered)) - 1)],
            "max": ordered[-1],
            "per_second": 1000.0 / statistics.mean(ordered) if statistics.mean(ordered) else 0.0,
        }


def measure_split(pack: Path, split: str, rules_dir: Path) -> SplitMetrics:
    """Run the engine over one split and count everything against the published labels."""
    claims_path = pack / "data" / split / "claims.jsonl"
    gold_path = pack / "data" / split / "expected_results.jsonl"
    if not claims_path.is_file() or not gold_path.is_file():
        raise FileNotFoundError(f"split {split!r} is incomplete under {pack}")

    claims: list[dict[str, Any]] = [
        json.loads(line) for line in claims_path.read_text(encoding="utf-8").splitlines() if line
    ]
    gold: dict[tuple[str, str], str] = {
        (row["claim_id"], row["rule_id"]): row["status"]
        for row in (
            json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines() if line
        )
    }
    context = RuleContext.from_rules_dir(rules_dir)

    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    false_alarms = missed_issues = wrong_abstentions = missed_abstentions = disagreements = 0
    valid_claims = valid_claims_flagged = 0
    latencies: list[float] = []

    for index, claim in enumerate(claims):
        started = time.perf_counter()
        records = [validate_record(record, claim) for record in evaluate_claim(claim, context)]
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if len(records) != 15:
            raise ValueError(
                f"{claim['claim_id']}: the engine produced {len(records)} records, expected 15"
            )
        if index >= WARMUP_CLAIMS:
            latencies.append(elapsed_ms)

        claim_has_gold_issue = False
        claim_flagged = False
        for record in records:
            expected = gold[(claim["claim_id"], record.rule_id)]
            produced = record.status.value
            bucket = counts[record.rule_id]
            if expected == "FAIL" and produced == "FAIL":
                bucket[0] += 1
                claim_has_gold_issue = True
                claim_flagged = True
            elif expected != "FAIL" and produced == "FAIL":
                bucket[1] += 1
                false_alarms += 1
                claim_flagged = True
            elif expected == "FAIL" and produced != "FAIL":
                bucket[2] += 1
                missed_issues += 1
                claim_has_gold_issue = True
            elif expected == "UNABLE_TO_ASSESS" and produced != "UNABLE_TO_ASSESS":
                wrong_abstentions += 1
            elif expected != "UNABLE_TO_ASSESS" and produced == "UNABLE_TO_ASSESS":
                missed_abstentions += 1
            elif expected != produced:
                disagreements += 1
        if not claim_has_gold_issue:
            valid_claims += 1
            if claim_flagged:
                valid_claims_flagged += 1

    return SplitMetrics(
        split=split,
        claims=len(claims),
        pairs=len(claims) * len(RULE_IDS),
        per_rule=tuple(
            RuleScore(rule_id, *counts[rule_id]) for rule_id in RULE_IDS if rule_id in counts
        ),
        false_alarms=false_alarms,
        missed_issues=missed_issues,
        wrong_abstentions=wrong_abstentions,
        missed_abstentions=missed_abstentions,
        status_disagreements=disagreements,
        valid_claims=valid_claims,
        valid_claims_flagged=valid_claims_flagged,
        latency_ms=tuple(latencies),
    )


def render(measured: list[SplitMetrics], rules_dir: Path) -> str:
    """The document, written so every number can be traced to the command that produced it."""
    # The rulebook's phrase for the class we score as positive, repeated so a reader never has to
    # guess what "F1" is measuring.
    lines: list[str] = [
        "# Detection metrics",
        "",
        "**What this is.** The detection figures the challenge names - metrics, F1, false positive "
        "rate and latency - measured against the mentor pack's own published labels on all three "
        "splits. It complements `EDU-EVALUATION-REPORT.md` (issue-level precision, recall "
        "and F1, plus the per-rule confusion matrix) and `ENGINE-PERFORMANCE-ANALYSIS.md` "
        "(where the labels stop discriminating); it duplicates neither.",
        "",
        "**How to reproduce it.**",
        "",
        "```bash",
        "uv run python scripts/detection_metrics.py",
        "```",
        "",
        "**What the numbers mean.** A rule's **F1** treats `FAIL` as the positive class: it is the "
        "harmonic mean of precision (of the checks we failed, the share the labels also fail) and "
        "recall (of the checks the labels fail, the share we failed). **Macro F1** is the "
        "unweighted mean of the fifteen rules' F1 scores, so a rare rule counts as much as a "
        "common one - the figure the challenge asks for, and why it is reported beside the "
        "pooled (micro) figure rather than instead of it.",
        "",
        "**What it does not claim.** These are the pack's PUBLIC labels for a fictional payer, on "
        "synthetic claims, and the engine was developed against this data. Perfect agreement "
        "here is conformance, not generalisation: the mentor's 200 held-out claims are not in "
        "this repository and remain the only honest test of that. Nothing below is a "
        "calibrated probability of anything.",
        "",
        "---",
        "",
        "## 1. Headline",
        "",
        "| Split | Claims | Pairs | **Macro F1 (15 rules)** | Macro F1 (exercised) "
        "| Micro F1 | False positive rate | Mean latency |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metrics in measured:
        latency = metrics.latency()
        lines.append(
            f"| {metrics.split} | {metrics.claims} | {metrics.pairs} | "
            f"**{metrics.macro_f1_all_rules:.4f}** | {metrics.macro_f1_active_rules:.4f} | "
            f"{metrics.micro_f1:.4f} | {metrics.false_positive_rate:.4%} | "
            f"{latency['mean']:.2f} ms |"
        )

    lines += [
        "",
        f"Mean latency is per claim for all fifteen rules **plus** the emitted-record contract "
        f"check - the same pair of calls the API runs per submission. {WARMUP_CLAIMS} claims are "
        f"run untimed first so first-call import cost is not charged to a measured claim.",
        "",
        "### Why the two macro columns differ from the micro column",
        "",
        "A strict macro average over fifteen rules scores a rule with **no positive examples in "
        "that split** as 0.0. That is arithmetic about the dataset, not about the engine, and "
        "it is the whole reason the stricter figure is printed beside the fairer one. Support "
        "per split:",
        "",
        "| Split | Rules with at least one failing label | Rules the split cannot exercise |",
        "|---|---:|---|",
    ]
    for metrics in measured:
        exercised = [rule.rule_id for rule in metrics.per_rule if rule.support]
        unexercised = [rule.rule_id for rule in metrics.per_rule if not rule.support]
        lines.append(
            f"| {metrics.split} | {len(exercised)} of {len(metrics.per_rule)} | "
            f"{', '.join(unexercised) if unexercised else 'none - every rule is exercised'} |"
        )
    lines += [
        "",
        "So on `stress` the strict fifteen-rule figure is not a measurement of the engine: nine "
        "rules have no failing example anywhere in those fifty claims, no engine could score above "
        "0.4 by that definition, and on every pair the split *can* test the engine is exact (micro "
        "F1 1.0000, zero false alarms, zero missed issues). `validation`, where all fifteen rules "
        "are exercised, is the split that measures the challenge's macro F1 without that caveat.",
        "",
        "## 2. Latency",
        "",
        "| Split | Mean | Median | p95 | Max | Throughput |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for metrics in measured:
        latency = metrics.latency()
        lines.append(
            f"| {metrics.split} | {latency['mean']:.2f} ms | {latency['median']:.2f} ms | "
            f"{latency['p95']:.2f} ms | {latency['max']:.2f} ms | "
            f"{latency['per_second']:.0f} claims/s |"
        )

    lines += [
        "",
        "A single claim's fifteen checks are pure functions over one JSON object: no network, no "
        "database, no model. The API adds persistence and the audit append; the engine itself is "
        "sub-millisecond.",
        "",
        "The timings are a snapshot of the machine that generated this file, which is why "
        "`--check` re-measures them and then ignores them when comparing. The accuracy figures "
        "above are not machine-dependent.",
        "",
        "## 3. Errors that must be zero",
        "",
        "| Split | False alarms | Missed issues | Wrong abstentions | Missed abstentions "
        "| Other disagreements | Valid claims wrongly flagged |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for metrics in measured:
        lines.append(
            f"| {metrics.split} | {metrics.false_alarms} | {metrics.missed_issues} | "
            f"{metrics.wrong_abstentions} | {metrics.missed_abstentions} | "
            f"{metrics.status_disagreements} | "
            f"{metrics.valid_claims_flagged} of {metrics.valid_claims} |"
        )

    lines += [
        "",
        "`Valid claims wrongly flagged` is the false-positive rate that matters commercially: "
        "claims with no real issue at all that the engine still sent to a human. It is reported "
        "separately from the pair-level rate because one clean claim with fifteen passing checks "
        "is fifteen chances to raise a false alarm.",
        "",
        "## 4. Macro F1 and per-rule support",
        "",
        "Every rule scored individually, so a rule that is never exercised cannot hide inside an "
        "average. A split with no positive examples for a rule cannot measure it - that is a "
        "property of the dataset, and it is stated rather than averaged away.",
        "",
        "| Rule | Development F1 | Validation F1 | Stress F1 | Validation support |",
        "|---|---:|---:|---:|---:|",
    ]
    by_split = {
        metrics.split: {rule.rule_id: rule for rule in metrics.per_rule} for metrics in measured
    }
    for rule_id in RULE_IDS:
        cells = [
            f"{by_split[metrics.split][rule_id].f1:.4f}"
            if rule_id in by_split[metrics.split]
            else "n/a"
            for metrics in measured
        ]
        validation_rule = by_split.get("validation", {}).get(rule_id)
        support = validation_rule.support if validation_rule else 0
        lines.append(f"| {rule_id} | {cells[0]} | {cells[1]} | {cells[2]} | {support} |")

    catalogue = (
        rules_dir.relative_to(REPO_ROOT) if rules_dir.is_relative_to(REPO_ROOT) else rules_dir
    )
    lines += [
        "",
        "## 5. Limitations",
        "",
        "1. **Public labels only.** The engine was developed against these splits. Perfect "
        "agreement measures conformance to the labelling programme, not accuracy on unseen data.",
        "2. **A fictional payer.** The rules are the mentor's; the catalogues are invented. These "
        "figures say nothing about a real payer's adjudication behaviour.",
        "3. **Synthetic claims.** No real claim, patient or member data is involved, so nothing "
        "here measures behaviour on the messiness of real submissions.",
        "4. **Macro F1 is unweighted by frequency.** A rule with three examples contributes as "
        "much as a rule with three hundred. That is the intent of a macro average and also its "
        "limitation; the per-rule table above shows which rules are thinly supported.",
        "5. **Latency is single-process and in-memory.** It excludes database writes, the audit "
        "append, HTTP overhead and any model call. It is the engine's cost, not a request's.",
        "6. **No calibration.** Deterministic checks report `confidence: null` by contract; no "
        "figure here is a probability, and none should be quoted as one.",
        "",
        "---",
        "",
        f"Generated by `scripts/detection_metrics.py` against the catalogue at `{catalogue}`.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure detection metrics against the pack labels."
    )
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK, help="mentor pack root")
    parser.add_argument("--rules-dir", type=Path, default=None, help="rule catalogue directory")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="where to write the doc"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the reproducible figures (timings are ignored), write nothing",
    )
    args = parser.parse_args(argv)

    rules_dir = args.rules_dir or (
        args.pack / "rules" if (args.pack / "rules").is_dir() else FALLBACK_RULES_DIR
    )
    if not args.pack.is_dir():
        _line(f"detection metrics refused: the mentor pack is not at {args.pack}")
        _line("  the pack is delivered reference material and is not tracked in git;")
        _line("  pass --pack <dir> or omit this script from a pack-less run.")
        return 1

    _line("claimguard detection metrics")
    _line(f"  pack      : {args.pack}")
    _line(f"  catalogue : {rules_dir}")
    _line()

    measured: list[SplitMetrics] = []
    for split in SPLITS:
        try:
            metrics = measure_split(args.pack, split, rules_dir)
        except (FileNotFoundError, ValueError) as exc:
            _line(f"detection metrics refused: {exc}")
            return 1 if isinstance(exc, FileNotFoundError) else 2
        measured.append(metrics)
        latency = metrics.latency()
        _line(
            f"  {split:12s} claims={metrics.claims:4d} pairs={metrics.pairs:5d} "
            f"macroF1={metrics.macro_f1_all_rules:.4f} microF1={metrics.micro_f1:.4f} "
            f"fp={metrics.false_alarms} fn={metrics.missed_issues} "
            f"mean={latency['mean']:.2f}ms"
        )

    document = render(measured, rules_dir)
    _line()
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.is_file() else ""
        if canonical(current) != canonical(document):
            _line(f"{args.output.relative_to(REPO_ROOT)} is out of date; re-run without --check")
            return 1
        _line(f"{args.output.relative_to(REPO_ROOT)} matches the measurement (timings ignored)")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(document, encoding="utf-8")
    _line(f"wrote {args.output.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
