"""Versioned evaluation report for the ClaimGuard teaching benchmark.

Usage (from the repository root)::

    uv run python scripts/edu_report.py --split development \
        --output docs/verification/EDU-EVALUATION-REPORT.md

What one run does, in order:

1. **Runs the engine** (``python -m claimguard.edu.run``) over the split's claim file and the
   mentor pack's rule catalogue, unless ``--pred`` supplies an existing predictions file.
2. **Scores that file twice**: the mentor's own strict scorer (``<pack>/src/evaluate.py``,
   executed as a subprocess by ``scripts/edu_conformance.py``) and the independent conformance
   harness (admissibility re-checks, evidence re-resolution, independent metric arithmetic).
3. **Writes a versioned Markdown report**: dataset identity (splits, counts, live SHA-256
   digests and agreement with the pack's own ``SHA256SUMS.json``), engine/catalogue identity
   (source digests, git revision, catalogue version), the full metric set the pack defines, the
   per-rule table, the confusion matrix, an error analysis that names the rules with the
   thinnest support, and the pack's honesty statements.

A **rejected run is not a result**: if the mentor's scorer exits non-zero, or the engine cannot
produce a complete prediction file, no report is written and the rejection is echoed verbatim.
Every number in the report comes from this run — nothing is estimated, and a metric with an
empty denominator is printed as ``null``, never as 100%.

Exit codes: ``0`` report written and the harness conformant; ``1`` report written but the
harness non-conformant (the report states so); ``2`` refused (usage, IO, engine failure or a
scorer rejection).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from edu_conformance import (  # noqa: E402  (sibling module; sys.path fixed above)
    SPLITS,
    STATUSES,
    ConformanceError,
    SplitReport,
    SplitRequest,
    as_list,
    as_mapping,
    find_pack_root,
    load_jsonl,
    run_split,
    write_json,
)

#: Per-rule metric table columns (single definition, so header and rows cannot drift apart).
PER_RULE_COLUMNS: tuple[str, ...] = (
    "Rule",
    "n",
    "Expected FAIL",
    "tp",
    "fp",
    "fn",
    "tn",
    "Precision",
    "Recall",
    "F1",
    "False-alarm rate",
    "Status accuracy",
    "NOT_IMPLEMENTED",
)


def _table_header(columns: Sequence[str]) -> list[str]:
    return ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]


def _table_row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _support_phrase(item: RuleSupport) -> str:
    total = (
        item.expected_pass + item.positives + item.expected_unable + item.expected_not_applicable
    )
    return f"**{item.rule_id}** ({item.positives} expected FAIL of {total} pair(s))"


#: Version of this report's own format. Bump when the section set or a definition changes.
REPORT_FORMAT_VERSION = "1.0.0"
GENERATOR_DISPLAY = "scripts/edu_report.py"
DEFAULT_WORKDIR = "artifacts/edu-report"
DEFAULT_SCORER_TIMEOUT = 900.0
ENGINE_SOURCES: tuple[str, ...] = ("claimguard/edu/*.py", "claimguard/edu/rules/*.py")

EXIT_OK = 0
EXIT_NON_CONFORMANT = 1
EXIT_REFUSED = 2

#: Section headings the report must contain (used by the tests as the contract).
REQUIRED_SECTIONS: tuple[str, ...] = (
    "## Reproduction",
    "## Data discipline and dataset identity",
    "## Engine and catalogue identity",
    "## Scorer verdict and gates",
    "## Metrics",
    "## Error analysis",
    "## AI explanation evaluation",
    "## Human review and security",
    "## Honesty rules and limitations",
)

#: The rulebook edges our own decision record says the public labels cannot discriminate.
#: Written into the report so exact agreement is never read as proof of the rulebook's intent.
UNDISCRIMINATED_EDGES: tuple[str, ...] = (
    "cross-line authorization quantity aggregation",
    "R007's 0.01 tolerance at a rounding boundary",
    "whitespace-only strings against a non-empty check",
    "claims whose lines carry several service dates",
    "precedence between a proven violation and an unknown input on the same rule",
)

#: The pack's honesty rules, as text templates. ``honesty_statements`` renders them concretely;
#: the tests assert the rendered sentences appear verbatim in the report.
HONESTY_STATEMENTS: tuple[tuple[str, str], ...] = (
    (
        "Instructional oracle, not ground truth",
        "The labels in this pack are an instructional oracle for a fictional rulebook: they are "
        "neither clinical ground truth nor reimbursement ground truth, and agreement with them "
        "is not evidence of production readiness.",
    ),
    (
        "Dataset split",
        "This report covers the {split} split ({claims} claims, {results} claim-rule pairs) of "
        "the supplied synthetic teaching dataset; the mentor's 200 held-out claims were not used "
        "and are not reachable from this repository.",
    ),
    (
        "Labels cannot discriminate every edge",
        "The public labels cannot discriminate several rulebook edges, so exact agreement here "
        "does not prove the rulebook's intent is implemented: {edges}.",
    ),
    (
        "Evidence values do not prove relevance",
        "Re-resolving every evidence pointer against the original claim proves that the cited "
        "value exists and is exact; it does not prove that the cited field is relevant to the "
        "conclusion, which is a human-judgement question this generator cannot answer.",
    ),
    (
        "Explanations are scored manually",
        "Explanation quality is not scored by this generator: the pack requires manual 0/1 "
        "scoring of its supplied explanation cases, reported separately from the numbers here.",
    ),
    (
        "NOT_IMPLEMENTED counts as incorrect",
        "NOT_IMPLEMENTED is a visible incomplete result and counts against status accuracy: the "
        "mentor's scorer treats it as wrong, so an engine that abstains from a rule cannot score "
        "well by abstaining.",
    ),
    (
        "Synthetic data only, review not adjudication",
        "Every record is synthetic and this system reviews rather than adjudicates: it never "
        "approves, denies, prices or pays a claim, and nothing here is clinical advice.",
    ),
    (
        "Undefined metrics are null",
        "A precision, recall or rate whose denominator is empty is reported as null, never as "
        "100%.",
    ),
)

#: The pack's error-category definitions, restated from docs/07_Evaluation_and_Acceptance.md.
CATEGORY_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("false_alarm", "Predicted FAIL among pairs whose expected status is not FAIL (`fp`)."),
    ("missed_issue", "Expected FAIL but predicted a different status (`fn`)."),
    (
        "false_abstention",
        "Predicted unable-to-assess when the expected status is something else.",
    ),
    ("missed_abstention", "Expected unable-to-assess but predicted a different status."),
    (
        "other_status_disagreement",
        "A status disagreement that is none of the four categories above (for example expected "
        "PASS predicted NOT_IMPLEMENTED).",
    ),
)

STATUS_ORDER: tuple[str, ...] = (
    "PASS",
    "FAIL",
    "UNABLE_TO_ASSESS",
    "NOT_APPLICABLE",
    "NOT_IMPLEMENTED",
)


class ReportError(RuntimeError):
    """Raised when the generator cannot produce a report (usage, IO, engine or scorer failure)."""


# ---------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------


def _emit(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def fmt_ratio(value: Any, digits: int = 4) -> str:
    """Format a possibly-undefined metric: a number to ``digits`` places, ``null`` otherwise."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "null"
    return f"{float(value):.{digits}f}"


def fmt_int(value: Any) -> str:
    """Format a count, or ``null`` when the file does not carry one."""
    if isinstance(value, bool) or not isinstance(value, int):
        return "null"
    return str(value)


def _as_int(value: Any) -> int | None:
    return value if type(value) is int else None


def sha256_file(path: Path) -> str:
    """Streaming SHA-256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def count_jsonl_rows(path: Path) -> int:
    """Number of non-empty lines in a JSONL file."""
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def truncate(text: str, limit: int) -> str:
    """Deterministic truncation marker for table cells."""
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


# ---------------------------------------------------------------------------------------
# Identity capture
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FileIdentity:
    """One input file: what it is, where it is, its digest, and the pack manifest's digest."""

    label: str
    display: str
    sha256: str
    size_bytes: int
    manifest_sha256: str | None = None

    @property
    def manifest_agrees(self) -> bool | None:
        if self.manifest_sha256 is None:
            return None
        return self.manifest_sha256 == self.sha256

    def payload(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "path": self.display,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "manifest_sha256": self.manifest_sha256,
            "manifest_agrees": self.manifest_agrees,
        }


def file_identity(
    path: Path,
    label: str,
    *,
    display: str | None = None,
    manifest: Mapping[str, str] | None = None,
) -> FileIdentity:
    """Digest one file, recording the pack manifest's digest for the same path when known."""
    shown = display if display is not None else str(path)
    recorded = manifest.get(shown) if manifest is not None and display is not None else None
    return FileIdentity(
        label=label,
        display=shown,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        manifest_sha256=recorded,
    )


def combined_digest(identities: Sequence[FileIdentity]) -> str:
    """One digest over a sorted ``path + file digest`` list (order-independent identity)."""
    digest = hashlib.sha256()
    for identity in sorted(identities, key=lambda item: item.display):
        digest.update(f"{identity.display}\0{identity.sha256}\n".encode())
    return digest.hexdigest()


def load_manifest_checksums(pack_root: Path) -> dict[str, str]:
    """The pack's own ``SHA256SUMS.json`` (path -> digest); empty when absent or unreadable."""
    payload = as_mapping(_load_json(pack_root / "SHA256SUMS.json"))
    return {
        str(key): str(value)
        for key, value in payload.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def git_revision(repo_root: Path) -> str | None:
    """The current git revision, or ``None`` when git/the repository is unavailable."""
    executable = shutil.which("git")
    if executable is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [executable, "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    revision = completed.stdout.strip()
    return revision if completed.returncode == 0 and revision else None


@dataclass(frozen=True)
class SplitSummary:
    """One split as the pack's dataset manifest describes it."""

    split: str
    claims: int | None
    rule_results: int | None
    statuses: tuple[tuple[str, int], ...]

    def payload(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "claims": self.claims,
            "rule_results": self.rule_results,
            "statuses": dict(self.statuses),
        }


@dataclass(frozen=True)
class DatasetIdentity:
    """Dataset identity: the manifest's split table plus live digests of the scored inputs."""

    split: str
    manifest_display: str
    manifest_version: str
    manifest_generated_on: str
    manifest_synthetic: bool | None
    splits: tuple[SplitSummary, ...]
    inputs: tuple[FileIdentity, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "manifest": {
                "path": self.manifest_display,
                "version": self.manifest_version,
                "generated_on": self.manifest_generated_on,
                "synthetic": self.manifest_synthetic,
            },
            "splits": [item.payload() for item in self.splits],
            "inputs": [item.payload() for item in self.inputs],
        }


def dataset_identity(pack_root: Path, split: str) -> DatasetIdentity:
    """Read the pack's dataset manifest and digest every input file of the scored split."""
    manifest = as_mapping(_load_json(pack_root / "data" / "dataset_manifest.json"))
    manifest_checksums = load_manifest_checksums(pack_root)
    splits_payload = as_mapping(manifest.get("splits"))

    summaries: list[SplitSummary] = []
    for name in SPLITS:
        entry = as_mapping(splits_payload.get(name))
        statuses = as_mapping(entry.get("statuses"))
        summaries.append(
            SplitSummary(
                split=name,
                claims=_as_int(entry.get("claims")),
                rule_results=_as_int(entry.get("rule_results")),
                statuses=tuple(
                    sorted(
                        (str(key), value) for key, value in statuses.items() if type(value) is int
                    )
                ),
            )
        )

    data_dir = pack_root / "data" / split
    inputs: list[FileIdentity] = []
    for name in ("claims.jsonl", "expected_results.jsonl", "fhir_bundles.jsonl"):
        path = data_dir / name
        if path.is_file():
            relative = f"data/{split}/{name}"
            inputs.append(file_identity(path, name, display=relative, manifest=manifest_checksums))
    for path in sorted((data_dir / "csv").glob("*.csv")):
        relative = f"data/{split}/csv/{path.name}"
        inputs.append(file_identity(path, path.name, display=relative, manifest=manifest_checksums))

    return DatasetIdentity(
        split=split,
        manifest_display="data/dataset_manifest.json",
        manifest_version=str(manifest.get("version", "")),
        manifest_generated_on=str(manifest.get("generated_on", "")),
        manifest_synthetic=manifest.get("synthetic")
        if isinstance(manifest.get("synthetic"), bool)
        else None,
        splits=tuple(summaries),
        inputs=tuple(inputs),
    )


@dataclass(frozen=True)
class RuleCatalogueEntry:
    """One fictional rule as the catalogue declares it."""

    rule_id: str
    title: str
    severity: str
    version: str
    source: str

    def payload(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "severity": self.severity,
            "version": self.version,
            "source": self.source,
        }


@dataclass(frozen=True)
class EngineIdentity:
    """Engine identity: git revision, source digests, catalogue digests and rule metadata."""

    git_revision: str | None
    digest: str
    sources: tuple[FileIdentity, ...]
    catalogue_digest: str
    catalogue_files: tuple[FileIdentity, ...]
    catalogue: tuple[RuleCatalogueEntry, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "git_revision": self.git_revision,
            "engine_digest": self.digest,
            "engine_sources": [item.payload() for item in self.sources],
            "catalogue_digest": self.catalogue_digest,
            "catalogue_files": [item.payload() for item in self.catalogue_files],
            "catalogue": [entry.payload() for entry in self.catalogue],
        }


def load_catalogue(path: Path) -> tuple[RuleCatalogueEntry, ...]:
    """Read ``rules/rules.json`` into rule metadata (id, title, severity, version, source)."""
    entries: list[RuleCatalogueEntry] = []
    for item in as_list(_load_json(path)):
        entry = as_mapping(item)
        rule_id = entry.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id:
            continue
        entries.append(
            RuleCatalogueEntry(
                rule_id=rule_id,
                title=str(entry.get("title", "")),
                severity=str(entry.get("severity", "")),
                version=str(entry.get("version", "")),
                source=str(entry.get("source", "")),
            )
        )
    return tuple(sorted(entries, key=lambda item: item.rule_id))


def engine_identity(repo_root: Path, rules_dir: Path) -> EngineIdentity:
    """Digest our engine sources and the pack's rule catalogue."""
    sources: list[FileIdentity] = []
    for pattern in ENGINE_SOURCES:
        for path in sorted(repo_root.glob(pattern)):
            sources.append(
                file_identity(
                    path,
                    path.name,
                    display=path.relative_to(repo_root).as_posix(),
                )
            )
    catalogue_files: list[FileIdentity] = []
    for path in sorted(rules_dir.glob("*.json")):
        catalogue_files.append(file_identity(path, path.name, display=f"<pack>/rules/{path.name}"))
    return EngineIdentity(
        git_revision=git_revision(repo_root),
        digest=combined_digest(sources),
        sources=tuple(sources),
        catalogue_digest=combined_digest(catalogue_files),
        catalogue_files=tuple(catalogue_files),
        catalogue=load_catalogue(rules_dir / "rules.json"),
    )


# ---------------------------------------------------------------------------------------
# Engine invocation and scoring
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineRun:
    """Outcome of one ``python -m claimguard.edu.run`` subprocess call."""

    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    output: Path

    def payload(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "exit_code": self.exit_code,
            "output": str(self.output),
        }


def run_engine(
    *,
    python: str,
    claims: Path,
    rules_dir: Path,
    output: Path,
    timeout: float,
) -> EngineRun:
    """Run the engine CLI over one claim file, writing the predictions JSONL."""
    command = [
        python,
        "-m",
        "claimguard.edu.run",
        "--claims",
        str(claims),
        "--rules-dir",
        str(rules_dir),
        "--output",
        str(output),
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
            command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReportError(f"the engine could not run: {exc}") from exc
    return EngineRun(
        command=tuple(command),
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        output=output,
    )


def score_predictions(
    *,
    pack_root: Path,
    split: str,
    pred: Path,
    python: str,
    workdir: Path,
    min_accuracy: float,
    accuracy_scope: str,
    timeout: float,
) -> SplitReport:
    """Score one predictions file with the mentor's oracle plus the independent harness."""
    request = SplitRequest(
        split=split,
        pred=pred,
        pack_root=pack_root,
        python=python,
        workdir=workdir,
        min_accuracy=min_accuracy,
        accuracy_scope=accuracy_scope,
        timeout=timeout,
    )
    try:
        return run_split(request)
    except ConformanceError as exc:
        raise ReportError(f"the conformance harness could not reach a verdict: {exc}") from exc


# ---------------------------------------------------------------------------------------
# Error analysis and support
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Mismatch:
    """One claim-rule pair whose predicted status differs from the expected status."""

    claim_id: str
    rule_id: str
    expected: str
    predicted: str
    evidence: tuple[tuple[str, str], ...]
    corrective_action: str

    @property
    def categories(self) -> tuple[str, ...]:
        return mismatch_categories(self.expected, self.predicted)

    def payload(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "rule_id": self.rule_id,
            "expected": self.expected,
            "predicted": self.predicted,
            "categories": list(self.categories),
            "evidence": [{"path": path, "value": value} for path, value in self.evidence],
            "corrective_action": self.corrective_action,
        }


def mismatch_categories(expected: str, predicted: str) -> tuple[str, ...]:
    """Which of the pack's error categories a disagreement belongs to.

    The predicates are exactly the oracle's own (``src/evaluate.py``), which is why one pair
    can belong to two categories at once: an expected FAIL predicted UNABLE_TO_ASSESS is both a
    missed issue (``fn``) and a false abstention. Anything else that disagrees is reported as
    ``other_status_disagreement``, a category the oracle has no column for.
    """
    categories: list[str] = []
    if predicted == "FAIL" and expected != "FAIL":
        categories.append("false_alarm")
    if expected == "FAIL" and predicted != "FAIL":
        categories.append("missed_issue")
    if predicted == "UNABLE_TO_ASSESS" and expected != "UNABLE_TO_ASSESS":
        categories.append("false_abstention")
    if expected == "UNABLE_TO_ASSESS" and predicted != "UNABLE_TO_ASSESS":
        categories.append("missed_abstention")
    if not categories and expected != predicted:
        categories.append("other_status_disagreement")
    return tuple(categories)


def _evidence_cells(row: Mapping[str, Any], limit: int = 120) -> tuple[tuple[str, str], ...]:
    cells: list[tuple[str, str]] = []
    for entry in as_list(row.get("evidence")):
        item = as_mapping(entry)
        path = item.get("path")
        if not isinstance(path, str):
            continue
        rendered = json.dumps(item.get("value"), ensure_ascii=False, sort_keys=True)
        cells.append((path, truncate(rendered, limit)))
    return tuple(cells)


#: Listing order for a truncated error list: the pack's most consequential category first.
CATEGORY_PRIORITY: tuple[str, ...] = (
    "missed_issue",
    "false_alarm",
    "false_abstention",
    "missed_abstention",
    "other_status_disagreement",
)


def _listing_priority(mismatch: Mismatch) -> int:
    categories = mismatch.categories
    if not categories:
        return len(CATEGORY_PRIORITY)
    return min(CATEGORY_PRIORITY.index(category) for category in categories)


def collect_mismatches(
    gold_rows: Sequence[Mapping[str, Any]],
    pred_rows: Sequence[Mapping[str, Any]],
    limit: int,
) -> tuple[Mismatch, ...]:
    """Enumerate status disagreements between gold and predictions.

    Ordered by the pack's error categories — missed issues first, then false alarms, the two
    abstention errors and finally anything the oracle has no column for — then by rule and claim
    id, so a truncated list shows the most consequential errors rather than an alphabetical slice.
    ``limit`` < 0 returns every disagreement.
    """
    gold = {
        (row.get("claim_id"), row.get("rule_id")): row
        for row in gold_rows
        if isinstance(row.get("claim_id"), str) and isinstance(row.get("rule_id"), str)
    }
    pred = {
        (row.get("claim_id"), row.get("rule_id")): row
        for row in pred_rows
        if isinstance(row.get("claim_id"), str) and isinstance(row.get("rule_id"), str)
    }
    mismatches: list[Mismatch] = []
    for key in sorted(set(gold) & set(pred), key=lambda item: (str(item[1]), str(item[0]))):
        gold_row = gold[key]
        pred_row = pred[key]
        expected = str(gold_row.get("status"))
        predicted = str(pred_row.get("status"))
        if expected == predicted:
            continue
        corrective = pred_row.get("corrective_action")
        mismatches.append(
            Mismatch(
                claim_id=str(key[0]),
                rule_id=str(key[1]),
                expected=expected,
                predicted=predicted,
                evidence=_evidence_cells(pred_row),
                corrective_action=corrective if isinstance(corrective, str) else "",
            )
        )
    mismatches.sort(
        key=lambda item: (_listing_priority(item), item.rule_id, item.claim_id),
    )
    if limit >= 0:
        return tuple(mismatches[:limit])
    return tuple(mismatches)


def category_counts(mismatches: Sequence[Mismatch]) -> dict[str, int]:
    """Count mismatches per category (the oracle's definitions plus ``other``)."""
    counts = {name: 0 for name, _ in CATEGORY_DEFINITIONS}
    for mismatch in mismatches:
        for category in mismatch.categories:
            counts[category] = counts.get(category, 0) + 1
    return counts


def cross_check_categories(counts: Mapping[str, int], overall: Mapping[str, Any]) -> list[str]:
    """The enumerated categories must reproduce the oracle's own aggregates."""
    problems: list[str] = []
    expected_pairs: tuple[tuple[str, str], ...] = (
        ("false_alarm", "fp"),
        ("missed_issue", "fn"),
        ("false_abstention", "false_abstentions"),
        ("missed_abstention", "missed_abstentions"),
    )
    for category, oracle_key in expected_pairs:
        oracle_value = overall.get(oracle_key)
        if not isinstance(oracle_value, int):
            problems.append(f"oracle JSON has no integer '{oracle_key}' to cross-check")
            continue
        if counts.get(category, 0) != oracle_value:
            problems.append(
                f"enumerated {category}={counts.get(category, 0)} disagrees with the oracle's "
                f"{oracle_key}={oracle_value}"
            )
    return problems


@dataclass(frozen=True)
class RuleSupport:
    """How many labelled observations actually carry one rule's score."""

    rule_id: str
    expected_pass: int
    expected_fail: int
    expected_unable: int
    expected_not_applicable: int

    @property
    def positives(self) -> int:
        """Expected FAIL pairs: the recall denominator, i.e. the rule's positive support."""
        return self.expected_fail

    @property
    def discriminating(self) -> int:
        """Labels that distinguish this rule from a rubber stamp: every non-PASS label."""
        return self.expected_fail + self.expected_unable + self.expected_not_applicable

    @property
    def recall_step(self) -> float | None:
        """How far recall moves when one of these labels flips."""
        return 1.0 / self.positives if self.positives else None

    def payload(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "expected_pass": self.expected_pass,
            "expected_fail": self.expected_fail,
            "expected_unable_to_assess": self.expected_unable,
            "expected_not_applicable": self.expected_not_applicable,
            "positives": self.positives,
            "discriminating_labels": self.discriminating,
            "recall_step": self.recall_step,
        }


def expected_status_counts(gold_rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """Expected-status histogram per rule, straight from the gold file."""
    counts: dict[str, dict[str, int]] = {}
    for row in gold_rows:
        rule_id = row.get("rule_id")
        status = row.get("status")
        if not isinstance(rule_id, str) or not isinstance(status, str):
            continue
        bucket = counts.setdefault(rule_id, {})
        bucket[status] = bucket.get(status, 0) + 1
    return counts


def support_analysis(
    gold_rows: Sequence[Mapping[str, Any]],
    catalogue: Sequence[RuleCatalogueEntry],
) -> tuple[RuleSupport, ...]:
    """Per-rule label support, thinnest (fewest expected FAILs) first."""
    counts = expected_status_counts(gold_rows)
    rules = sorted(set(counts) | {entry.rule_id for entry in catalogue})
    supports = [
        RuleSupport(
            rule_id=rule_id,
            expected_pass=counts.get(rule_id, {}).get("PASS", 0),
            expected_fail=counts.get(rule_id, {}).get("FAIL", 0),
            expected_unable=counts.get(rule_id, {}).get("UNABLE_TO_ASSESS", 0),
            expected_not_applicable=counts.get(rule_id, {}).get("NOT_APPLICABLE", 0),
        )
        for rule_id in rules
    ]
    return tuple(sorted(supports, key=lambda item: (item.positives, item.rule_id)))


# ---------------------------------------------------------------------------------------
# Reference ablation: the pack's own baseline
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BaselineSummary:
    """The pack's own 3-rule baseline, scored by the same oracle for comparison."""

    command: tuple[str, ...]
    stdout: str
    predictions: FileIdentity
    scorer_exit_code: int
    metrics: dict[str, Any]
    mismatches: tuple[Mismatch, ...]
    failure_reasons: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "predictions": self.predictions.payload(),
            "scorer_exit_code": self.scorer_exit_code,
            "metrics": self.metrics,
            "failures": list(self.failure_reasons),
            "mismatches_shown": [item.payload() for item in self.mismatches],
        }


def run_baseline_ablation(
    *,
    pack_root: Path,
    split: str,
    python: str,
    workdir: Path,
    timeout: float,
    max_errors: int,
) -> BaselineSummary:
    """Run ``<pack>/src/run_baseline.py`` and score it, for the baseline comparison."""
    claims = pack_root / "data" / split / "claims.jsonl"
    output = workdir / split / "baseline_predictions.jsonl"
    command = [
        python,
        str(pack_root / "src" / "run_baseline.py"),
        "--input",
        str(claims),
        "--output",
        str(output),
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReportError(f"the pack baseline could not run: {exc}") from exc
    if completed.returncode != 0 or not output.is_file():
        raise ReportError(
            "the pack baseline did not produce predictions "
            f"(exit {completed.returncode}): {completed.stderr.strip()}"
        )

    report = score_predictions(
        pack_root=pack_root,
        split=split,
        pred=output,
        python=python,
        workdir=workdir / "baseline",
        min_accuracy=-1.0,  # the ablation is a comparison, not a gate
        accuracy_scope="implemented",
        timeout=timeout,
    )
    gold_rows = load_jsonl(pack_root / "data" / split / "expected_results.jsonl")
    mismatches = collect_mismatches(gold_rows, load_jsonl(output), max_errors)
    return BaselineSummary(
        command=tuple(command),
        stdout=completed.stdout or "",
        predictions=file_identity(
            output,
            "baseline predictions",
            display=f"{DEFAULT_WORKDIR}/{split}/baseline_predictions.jsonl",
        ),
        scorer_exit_code=report.scorer.exit_code,
        metrics=report.metrics if isinstance(report.metrics, dict) else {},
        mismatches=mismatches,
        failure_reasons=tuple(report.failure_reasons),
    )


# ---------------------------------------------------------------------------------------
# Report context and rendering
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportContext:
    """Everything the report renders. ``build_context`` is the production constructor."""

    split: str = ""
    generated_at: str = ""
    report_format_version: str = REPORT_FORMAT_VERSION
    command_line: str = ""
    engine_run: EngineRun | None = None
    predictions: FileIdentity | None = None
    predictions_source: str = ""
    dataset: DatasetIdentity | None = None
    engine: EngineIdentity | None = None
    scorer_command: tuple[str, ...] = ()
    scorer_exit_code: int = 0
    scorer_message: str = ""
    metrics_path: str = ""
    context_path: str = ""
    metrics: dict[str, Any] = field(default_factory=dict[str, Any])
    independent: dict[str, Any] = field(default_factory=dict[str, Any])
    audit: dict[str, Any] = field(default_factory=dict[str, Any])
    gate: dict[str, Any] = field(default_factory=dict[str, Any])
    failure_reasons: tuple[str, ...] = ()
    supports: tuple[RuleSupport, ...] = ()
    mismatches: tuple[Mismatch, ...] = ()
    mismatches_total: int = 0
    category_counts: dict[str, int] = field(default_factory=dict[str, int])
    claims: int = 0
    results: int = 0
    baseline: BaselineSummary | None = None
    baseline_error: str = ""
    max_errors: int = 25

    def payload(self) -> dict[str, Any]:
        return {
            "report_format_version": self.report_format_version,
            "generated_at": self.generated_at,
            "generator": {
                "path": GENERATOR_DISPLAY,
                "command_line": self.command_line,
            },
            "split": self.split,
            "claims": self.claims,
            "results": self.results,
            "predictions": self.predictions.payload() if self.predictions else None,
            "predictions_source": self.predictions_source,
            "engine_run": self.engine_run.payload() if self.engine_run else None,
            "dataset": self.dataset.payload() if self.dataset else None,
            "engine": self.engine.payload() if self.engine else None,
            "scorer": {
                "command": list(self.scorer_command),
                "exit_code": self.scorer_exit_code,
                "message": self.scorer_message,
                "metrics_path": self.metrics_path,
            },
            "metrics": self.metrics,
            "independent": self.independent,
            "independent_audit": self.audit,
            "gate": self.gate,
            "failure_reasons": list(self.failure_reasons),
            "support": [item.payload() for item in self.supports],
            "categories": dict(self.category_counts),
            "mismatches_total": self.mismatches_total,
            "mismatches_shown": [item.payload() for item in self.mismatches],
            "baseline": self.baseline.payload() if self.baseline else None,
            "baseline_error": self.baseline_error,
            "context_path": self.context_path,
        }


def honesty_statements(ctx: ReportContext) -> tuple[tuple[str, str], ...]:
    """The pack's honesty rules rendered for this run (the tests assert these appear verbatim)."""
    values = {
        "split": ctx.split,
        "claims": ctx.claims,
        "results": ctx.results,
        "edges": "; ".join(UNDISCRIMINATED_EDGES),
    }
    return tuple((label, text.format(**values)) for label, text in HONESTY_STATEMENTS)


def _overall(ctx: ReportContext) -> dict[str, Any]:
    return as_mapping(ctx.metrics.get("overall"))


def _by_rule(ctx: ReportContext) -> dict[str, Any]:
    return as_mapping(ctx.metrics.get("by_rule"))


def _citation(metric: str) -> str:
    return f"oracle `overall.{metric}`"


def _problem_count(ctx: ReportContext) -> int:
    return len(as_list(ctx.independent.get("problems")))


def _row(label: str, value: str, source: str) -> str:
    """One Markdown table row (kept as a call so the formatter can wrap it)."""
    return f"| {label} | {value} | {source} |"


def _pair_row(label: str, ours: Any, theirs: Any, *, ratio: bool = False, raw: bool = False) -> str:
    """One side-by-side comparison row for the reference ablation."""
    if raw:
        render: Any = str
    else:
        render = fmt_ratio if ratio else fmt_int
    return f"| {label} | {render(ours)} | {render(theirs)} |"


def _render_reproduction(ctx: ReportContext) -> list[str]:
    lines = [
        "The generator ran, in this order: the engine, the mentor's strict scorer, then the",
        "independent conformance harness. Each block is the literal argv of this run; the",
        "placeholder form below it is the equivalent operator entry point, where `<pack>` is the",
        "absolute path visible in the literal command.",
        "",
    ]
    if ctx.engine_run is not None:
        lines.extend(
            [
                "**Engine** (`python -m claimguard.edu.run`), literal argv:",
                "",
                "```bash",
                " ".join(_shell(part) for part in ctx.engine_run.command),
                "```",
                "",
                f"Exit code {ctx.engine_run.exit_code}; stderr (verbatim):",
                "",
                "```text",
                *((ctx.engine_run.stderr.strip() or "(no output)").splitlines()),
                "```",
                "",
                "```bash",
                "uv run python -m claimguard.edu.run --claims <pack>/data/"
                f"{ctx.split}/claims.jsonl --rules-dir <pack>/rules "
                f"--output <workdir>/{ctx.split}/predictions.jsonl",
                "```",
            ]
        )
    else:
        lines.append("**Engine**: not run — the predictions were supplied with `--pred`.")
    lines.append("")
    if ctx.scorer_command:
        lines.extend(
            [
                "**Mentor's strict scorer** (`<pack>/src/evaluate.py`), literal argv:",
                "",
                "```bash",
                " ".join(_shell(part) for part in ctx.scorer_command),
                "```",
                "",
                f"Exit code **{ctx.scorer_exit_code}** (0 = accepted). Metrics JSON: "
                f"`{ctx.metrics_path}`.",
            ]
        )
    else:
        lines.append("**Mentor's strict scorer**: not invoked for this report.")
    lines.append("")
    lines.append("**Independent conformance harness** (`scripts/edu_conformance.py`):")
    lines.append("")
    lines.append("```bash")
    lines.append(
        "uv run python scripts/edu_conformance.py --pred "
        f"{_shell(str(ctx.predictions.display) if ctx.predictions else '<predictions>')} "
        f"--split {ctx.split} --workdir {_shell(Path(ctx.metrics_path).parent.parent.as_posix())} "
        f"--accuracy-scope {ctx.gate.get('scope', 'implemented')} "
        f"--min-accuracy {ctx.gate.get('min_accuracy', '')}"
    )
    lines.append("```")
    lines.append("")
    lines.append("**This report:**")
    lines.append("")
    lines.append("```bash")
    lines.append(f"uv run python {GENERATOR_DISPLAY} {ctx.command_line}".rstrip())
    lines.append("```")
    lines.append("")
    lines.append(
        f"Generator: `{GENERATOR_DISPLAY}` (format version {ctx.report_format_version}); "
        f"generated {ctx.generated_at}; interpreter `{sys.executable}`."
    )
    lines.append("")
    lines.append(
        "Machine-readable context written alongside the report (every number in this report is "
        f"a field of it): `{ctx.context_path}`."
    )
    return lines


def _shell(part: str) -> str:
    return f'"{part}"' if " " in part else part


def _render_data_discipline(ctx: ReportContext) -> list[str]:
    lines = [
        "All supplied data is synthetic. The pack's protocol is that development is the open",
        "development set, the validation labels must be disclosed as development feedback once",
        "they influence development, and the stress split tests robustness rather than a",
        "representative prevalence sample (docs/07_Evaluation_and_Acceptance.md).",
        "",
        "**Our disclosure:** we have scored all three public splits (see",
        "`docs/verification/EDU-PACK-CONFORMANCE.md`), so the validation labels are development",
        "feedback for us and are treated as such. No split in this repository is naive to us any",
        "more; the mentor's 200 held-out claims are the only untouched evidence, and they are not",
        "in this repository and were not used.",
        "",
    ]
    if ctx.dataset is None:
        lines.append("Dataset manifest: not recorded for this run.")
        return lines
    dataset = ctx.dataset
    lines.extend(
        [
            f"Manifest `{dataset.manifest_display}`: version `{dataset.manifest_version}`, "
            f"generated {dataset.manifest_generated_on}, synthetic="
            f"`{dataset.manifest_synthetic}`.",
            "",
            "| Split | Claims | Claim-rule pairs | Expected statuses |",
            "|---|---:|---:|---|",
        ]
    )
    for summary in dataset.splits:
        statuses = ", ".join(f"{name} {count}" for name, count in summary.statuses)
        lines.append(
            f"| {summary.split} | {fmt_int(summary.claims)} | {fmt_int(summary.rule_results)} | "
            f"{statuses or 'null'} |"
        )
    lines.extend(
        [
            "",
            f"Inputs of the scored **{ctx.split}** split, with live SHA-256 digests and the "
            "pack manifest's own recorded digest for the same path:",
            "",
            "| Input | Bytes | SHA-256 (this run) | SHA-256 (pack manifest) | Agreement |",
            "|---|---:|---|---|---|",
        ]
    )
    for identity in dataset.inputs:
        agreement = identity.manifest_agrees
        if agreement is None:
            mark = "not in manifest"
        elif agreement:
            mark = "match"
        else:
            mark = "MISMATCH"
        lines.append(
            f"| `{identity.display}` | {identity.size_bytes} | `{identity.sha256}` | "
            f"`{identity.manifest_sha256 or '—'}` | {mark} |"
        )
    return lines


def _render_identity(ctx: ReportContext) -> list[str]:
    if ctx.engine is None:
        return ["Engine identity: not recorded for this run."]
    engine = ctx.engine
    lines = [
        f"Engine revision: `{engine.git_revision or 'unavailable (no git metadata)'}`. The "
        "working tree may carry uncommitted work; the source digest below is the authoritative "
        "identity of the code that produced these numbers.",
        "",
        f"Engine source digest: `{engine.digest}` over {len(engine.sources)} file(s):",
        "",
        "| Source | SHA-256 |",
        "|---|---|",
    ]
    for identity in engine.sources:
        lines.append(f"| `{identity.display}` | `{identity.sha256}` |")
    lines.extend(
        [
            "",
            f"Rule catalogue digest: `{engine.catalogue_digest}` over "
            f"{len(engine.catalogue_files)} file(s):",
            "",
            "| Catalogue file | SHA-256 |",
            "|---|---|",
        ]
    )
    for identity in engine.catalogue_files:
        lines.append(f"| `{identity.display}` | `{identity.sha256}` |")
    lines.extend(
        [
            "",
            f"The {len(engine.catalogue)} fictional rules the engine implements, as the catalogue "
            "declares them:",
            "",
            "| Rule | Title | Severity | Version | Source |",
            "|---|---|---|---|---|",
        ]
    )
    for entry in engine.catalogue:
        lines.append(
            f"| {entry.rule_id} | {entry.title} | {entry.severity} | {entry.version} | "
            f"`{entry.source}` |"
        )
    return lines


def _render_verdict(ctx: ReportContext) -> list[str]:
    overall = _overall(ctx)
    conformant = not ctx.failure_reasons
    lines = [
        f"**Verdict: {'CONFORMANT' if conformant else 'NON-CONFORMANT'}** — the mentor's scorer "
        f"exited {ctx.scorer_exit_code} (0 = the predictions are admissible).",
        "",
    ]
    if ctx.scorer_message.strip():
        lines.extend(["The scorer's own output, verbatim:", "", "```text"])
        lines.extend(ctx.scorer_message.strip().splitlines())
        lines.extend(["```", ""])
    if ctx.predictions is not None:
        lines.extend(
            [
                f"Predictions scored: `{ctx.predictions.display}` (sha256 "
                f"`{ctx.predictions.sha256}`, {ctx.predictions.size_bytes} bytes), "
                f"{ctx.predictions_source}.",
                "",
            ]
        )
    lines.extend(
        [
            "| Check | Value | Source |",
            "|---|---|---|",
            f"| Oracle claim-rule pairs | {fmt_int(overall.get('count'))} | {_citation('count')} |",
            f"| Independent admissibility problems | {_problem_count(ctx)} | "
            "harness `independent.problems` |",
            f"| Evidence pointers re-resolved against the original claims | "
            f"{fmt_int(ctx.independent.get('evidence_pointers'))} | harness `independent` |",
            f"| Independent recomputation of `status_accuracy` | "
            f"{fmt_ratio(ctx.audit.get('status_accuracy'))} | harness arithmetic over gold+pred |",
            f"| Implemented accuracy (pairs the engine committed to) | "
            f"{fmt_ratio(ctx.audit.get('implemented_accuracy'))} over "
            f"{fmt_int(ctx.audit.get('implemented_pairs'))} pair(s) | harness arithmetic |",
            f"| Accuracy gate | scope={ctx.gate.get('scope', '')} "
            f"min={ctx.gate.get('min_accuracy', '')} "
            f"accuracy={fmt_ratio(ctx.gate.get('accuracy'))} → "
            f"{'PASS' if ctx.gate.get('passed') else 'FAIL'} | harness `gate` |",
            "",
            "The gate is applied to the scope named above; it does not replace the oracle's raw",
            "`status_accuracy`, which is reported in the metric set below and covers every pair",
            "including any `NOT_IMPLEMENTED`.",
        ]
    )
    if ctx.failure_reasons:
        lines.extend(["", "Failure reasons recorded by the harness:", ""])
        lines.extend(f"- {reason}" for reason in ctx.failure_reasons)
    return lines


def _render_metrics(ctx: ReportContext) -> list[str]:
    overall = _overall(ctx)
    exact = ctx.metrics.get("claims_with_all_statuses_correct")
    exact_ratio = exact / ctx.claims if type(exact) is int and ctx.claims else None
    lines = [
        "All metrics are at claim-rule level unless labelled otherwise, and every value below is",
        "the mentor's scorer JSON for this run (`overall` inside the metrics file).",
        "",
        "| Metric | Value | Definition / source |",
        "|---|---|---|",
        _row("Claim-rule pairs scored", fmt_int(overall.get("count")), "`overall.count`"),
        _row(
            "True positives (expected FAIL, predicted FAIL)",
            fmt_int(overall.get("tp")),
            "`overall.tp`",
        ),
        _row("False positives", fmt_int(overall.get("fp")), "`overall.fp`"),
        _row("False negatives", fmt_int(overall.get("fn")), "`overall.fn`"),
        _row("True negatives (neither side FAIL)", fmt_int(overall.get("tn")), "`overall.tn`"),
        _row(
            "Issue precision",
            fmt_ratio(overall.get("issue_precision")),
            "TP / (TP+FP); null when no FAIL is predicted",
        ),
        _row(
            "Issue recall",
            fmt_ratio(overall.get("issue_recall")),
            "TP / (TP+FN); null when no FAIL is expected",
        ),
        _row("Issue F1", fmt_ratio(overall.get("issue_f1")), "harmonic balance of the two"),
        _row(
            "False-alarm rate",
            fmt_ratio(overall.get("false_alarm_rate")),
            "predicted FAIL among pairs whose expected status is not FAIL",
        ),
        _row(
            "Status accuracy",
            fmt_ratio(overall.get("status_accuracy")),
            "exact agreement across all five statuses",
        ),
        _row(
            "False abstentions",
            fmt_int(overall.get("false_abstentions")),
            "predicted unable-to-assess, expected something else",
        ),
        _row(
            "Missed abstentions",
            fmt_int(overall.get("missed_abstentions")),
            "expected unable-to-assess, predicted something else",
        ),
        _row(
            "NOT_IMPLEMENTED predictions",
            fmt_int(overall.get("not_implemented")),
            "visible incomplete results; counted as incorrect by the scorer",
        ),
        _row(
            "Claim exact match",
            f"{fmt_int(exact)} / {ctx.claims} = {fmt_ratio(exact_ratio)}",
            "all 15 rule statuses correct for a claim (`claims_with_all_statuses_correct`)",
        ),
        "",
        "### Issue detection",
        "",
        f"Issue precision {fmt_ratio(overall.get('issue_precision'))}, recall "
        f"{fmt_ratio(overall.get('issue_recall'))}, F1 {fmt_ratio(overall.get('issue_f1'))}. "
        f"False alarms: {fmt_int(overall.get('fp'))} pair(s) flagged FAIL where the expected "
        f"status is not FAIL. Missed issues: {fmt_int(overall.get('fn'))} expected FAIL pair(s) "
        "not flagged FAIL. Both are enumerated in the error analysis below.",
        "",
        "### Uncertainty handling",
        "",
        f"False abstentions: {fmt_int(overall.get('false_abstentions'))} pair(s) where the engine "
        "answered unable-to-assess although the expected status is known; missed abstentions: "
        f"{fmt_int(overall.get('missed_abstentions'))} pair(s) where the expected status is "
        "unable-to-assess and the engine answered something else. Abstention is a distinct",
        "outcome here: neither number is folded into the precision/recall pair above.",
        "",
        "### Claim exact match",
        "",
        f"{fmt_int(exact)} of {ctx.claims} claim(s) have every one of their 15 statuses correct "
        f"({fmt_ratio(exact_ratio)}). NOT_IMPLEMENTED counts as incorrect, so an engine that "
        "abstains from rules cannot reach a high number here by abstaining.",
        "",
        "### Per-rule results",
        "",
        *_table_header(PER_RULE_COLUMNS),
    ]
    support_by_rule = {item.rule_id: item for item in ctx.supports}
    by_rule = _by_rule(ctx)
    for rule_id in sorted(by_rule):
        entry = as_mapping(by_rule[rule_id])
        support = support_by_rule.get(rule_id)
        lines.append(
            _table_row(
                (
                    rule_id,
                    fmt_int(entry.get("count")),
                    fmt_int(support.positives) if support else "null",
                    fmt_int(entry.get("tp")),
                    fmt_int(entry.get("fp")),
                    fmt_int(entry.get("fn")),
                    fmt_int(entry.get("tn")),
                    fmt_ratio(entry.get("issue_precision")),
                    fmt_ratio(entry.get("issue_recall")),
                    fmt_ratio(entry.get("issue_f1")),
                    fmt_ratio(entry.get("false_alarm_rate")),
                    fmt_ratio(entry.get("status_accuracy")),
                    fmt_int(entry.get("not_implemented")),
                )
            )
        )
    lines.extend(["", "### Confusion matrix", "", _confusion_table(ctx), ""])
    lines.extend(_render_ablation(ctx))
    return lines


def _confusion_table(ctx: ReportContext) -> str:
    cells: dict[tuple[str, str], int] = {}
    for item in as_list(ctx.metrics.get("confusion")):
        entry = as_mapping(item)
        expected = entry.get("expected")
        predicted = entry.get("predicted")
        count = _as_int(entry.get("count"))
        if isinstance(expected, str) and isinstance(predicted, str) and count is not None:
            cells[(expected, predicted)] = count
    observed = {name for pair in cells for name in pair}
    order = list(STATUS_ORDER) + sorted(observed - set(STATUS_ORDER) - set(STATUSES))
    order += sorted(name for name in observed - set(STATUS_ORDER) if name in STATUSES)
    header = "| Expected \\ Predicted | " + " | ".join(order) + " |"
    divider = "|---" * (len(order) + 1) + "|"
    rows = [header, divider]
    for expected in order:
        values = " | ".join(fmt_int(cells.get((expected, predicted), 0)) for predicted in order)
        rows.append(f"| {expected} | {values} |")
    return "\n".join(rows)


def _render_ablation(ctx: ReportContext) -> list[str]:
    lines = ["", "### Reference ablation: the pack's own baseline", ""]
    if ctx.baseline is None:
        if ctx.baseline_error:
            lines.append(
                "The ablation was requested but did not run: "
                f"{ctx.baseline_error}. Nothing is estimated in its place."
            )
        else:
            lines.append(
                "Not computed in this run (`--no-baseline` was given). Nothing is estimated in "
                "its place."
            )
        return lines
    baseline = ctx.baseline
    theirs = as_mapping(baseline.metrics.get("overall"))
    ours = _overall(ctx)
    exact_ours = ctx.metrics.get("claims_with_all_statuses_correct")
    exact_theirs = baseline.metrics.get("claims_with_all_statuses_correct")
    lines.extend(
        [
            "The pack ships a 3-rule reference engine. It is scored here by the same oracle on",
            "the same split, as a floor for comparison — it is the mentor's own code, not our",
            "AI layer, and its implementation line is quoted verbatim:",
            "",
            "```text",
            (baseline.stdout.strip() or "(no output)"),
            "```",
            "",
            "| Metric | Our engine | Pack baseline |",
            "|---|---|---|",
            _pair_row("Claim-rule pairs", ours.get("count"), theirs.get("count")),
            _pair_row(
                "Issue precision",
                ours.get("issue_precision"),
                theirs.get("issue_precision"),
                ratio=True,
            ),
            _pair_row(
                "Issue recall", ours.get("issue_recall"), theirs.get("issue_recall"), ratio=True
            ),
            _pair_row("Issue F1", ours.get("issue_f1"), theirs.get("issue_f1"), ratio=True),
            _pair_row(
                "False-alarm rate",
                ours.get("false_alarm_rate"),
                theirs.get("false_alarm_rate"),
                ratio=True,
            ),
            _pair_row(
                "Status accuracy",
                ours.get("status_accuracy"),
                theirs.get("status_accuracy"),
                ratio=True,
            ),
            _pair_row(
                "False abstentions",
                ours.get("false_abstentions"),
                theirs.get("false_abstentions"),
            ),
            _pair_row(
                "Missed abstentions",
                ours.get("missed_abstentions"),
                theirs.get("missed_abstentions"),
            ),
            _pair_row(
                "NOT_IMPLEMENTED", ours.get("not_implemented"), theirs.get("not_implemented")
            ),
            _pair_row(
                "Claim exact match",
                f"{fmt_int(exact_ours)} / {ctx.claims}",
                f"{fmt_int(exact_theirs)} / {ctx.claims}",
                raw=True,
            ),
            "",
            f"Baseline predictions: `{baseline.predictions.display}` "
            f"(`{baseline.predictions.sha256}`), scored with the gate disabled "
            f"(oracle exit {baseline.scorer_exit_code}). Its {fmt_int(theirs.get('fn'))} missed "
            "issue(s) are examples of the error class our engine does not currently produce; the "
            "first ones are listed in the error analysis.",
        ]
    )
    return lines


def _render_error_analysis(ctx: ReportContext) -> list[str]:
    overall = _overall(ctx)
    lines = [
        "Categories are the pack's own definitions, recomputed from the gold and prediction files",
        "and cross-checked against the oracle's JSON; a pair can fall into two categories, which",
        "is exactly how the oracle counts it (for example an expected FAIL answered",
        "unable-to-assess is both a missed issue and a false abstention).",
        "",
        "| Category | Pairs | Oracle's own count | Agrees |",
        "|---|---:|---:|---|",
    ]
    oracle_keys = {
        "false_alarm": "fp",
        "missed_issue": "fn",
        "false_abstention": "false_abstentions",
        "missed_abstention": "missed_abstentions",
    }
    for name in (name for name, _ in CATEGORY_DEFINITIONS):
        oracle_key = oracle_keys.get(name)
        oracle_value = overall.get(oracle_key) if oracle_key else None
        agrees = (
            "—"
            if oracle_key is None
            else ("yes" if ctx.category_counts.get(name, 0) == oracle_value else "NO")
        )
        shown = fmt_int(oracle_value) if oracle_key else "no column"
        lines.append(
            f"| {name} | {fmt_int(ctx.category_counts.get(name, 0))} | {shown} | {agrees} |"
        )
    lines.extend(["", "The categories are:", ""])
    lines.extend(f"- `{name}` — {definition}" for name, definition in CATEGORY_DEFINITIONS)
    lines.extend(
        [
            "",
            f"Status disagreements on this split: {ctx.mismatches_total} of "
            f"{fmt_int(overall.get('count'))} pair(s).",
            "",
        ]
    )
    if ctx.mismatches_total == 0:
        lines.extend(
            [
                "There are **no false alarms and no missed issues** on this split, so the pack's",
                "template request for at least five false or missed findings *with Claim ID, Rule",
                "ID and evidence* cannot be satisfied from this run. We do not manufacture them.",
                "The closest honest substitute is the support analysis below plus the reference",
                "ablation: the pack baseline's own misses are enumerated after it.",
                "",
            ]
        )
    if ctx.mismatches:
        lines.extend(
            [
                f"{len(ctx.mismatches)} of {ctx.mismatches_total} disagreement(s), missed issues "
                "first, with the prediction's own evidence:",
                "",
                "| Claim ID | Rule ID | Expected | Predicted | Categories | Evidence cited | "
                "Corrective action |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for mismatch in ctx.mismatches:
            evidence = (
                "; ".join(f"`{path}` = `{value}`" for path, value in mismatch.evidence)
                or "none cited"
            )
            lines.append(
                f"| {mismatch.claim_id} | {mismatch.rule_id} | {mismatch.expected} | "
                f"{mismatch.predicted} | {', '.join(mismatch.categories)} | {evidence} | "
                f"{truncate(mismatch.corrective_action, 120) or '—'} |"
            )
        lines.append("")
    if ctx.baseline is not None and ctx.baseline.mismatches:
        overall_baseline = as_mapping(ctx.baseline.metrics.get("overall"))
        lines.extend(
            [
                f"**Reference ablation errors** — the pack baseline's "
                f"{len(ctx.baseline.mismatches)} most consequential enumerated status "
                f"disagreement(s), missed issues first; the oracle counts "
                f"{fmt_int(overall_baseline.get('fp'))} false alarm(s) and "
                f"{fmt_int(overall_baseline.get('fn'))} missed issue(s) for it on this split.",
                "Where the baseline left a rule unimplemented it cited no evidence at all, so the",
                "template's 'with evidence' column is honestly empty:",
                "",
                "| Claim ID | Rule ID | Expected | Predicted | Categories | Evidence cited |",
                "|---|---|---|---|---|---|",
            ]
        )
        for mismatch in ctx.baseline.mismatches:
            evidence = (
                "; ".join(f"`{path}` = `{value}`" for path, value in mismatch.evidence)
                or "none cited (`NOT_IMPLEMENTED` carries no evidence)"
            )
            lines.append(
                f"| {mismatch.claim_id} | {mismatch.rule_id} | {mismatch.expected} | "
                f"{mismatch.predicted} | {', '.join(mismatch.categories)} | {evidence} |"
            )
        lines.append("")
    lines.extend(_render_support(ctx))
    return lines


def _render_support(ctx: ReportContext) -> list[str]:
    lines = [
        "### Support: which rules carry the thinnest evidence",
        "",
        "A perfect score on a rule with three expected FAILs rests on three observations. The",
        "table ranks every rule by positive support (expected FAIL pairs — the recall",
        "denominator) so the weakest claims are visible instead of hidden by the overall average:",
        "",
        "| Rule | Expected PASS | Expected FAIL | Expected unable | Expected N/A | "
        "Discriminating labels | One flip moves recall by |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for support in ctx.supports:
        step = (
            f"{support.recall_step * 100:.2f} pts"
            if support.recall_step is not None
            else "recall undefined"
        )
        lines.append(
            f"| {support.rule_id} | {support.expected_pass} | {support.expected_fail} | "
            f"{support.expected_unable} | {support.expected_not_applicable} | "
            f"{support.discriminating} | {step} |"
        )
    lines.append("")
    by_positives = list(ctx.supports)
    thinnest = by_positives[:3]
    by_discriminating = sorted(ctx.supports, key=lambda item: (item.discriminating, item.rule_id))
    weakest = by_discriminating[:3]
    lines.append(
        "Thinnest positive support (fewest expected FAILs): "
        + ", ".join(_support_phrase(item) for item in thinnest)
        + "."
    )
    lines.append("")
    lines.append(
        "Thinnest discriminating support (fewest labels that are not PASS): "
        + ", ".join(f"**{item.rule_id}** ({item.discriminating} label(s))" for item in weakest)
        + "."
    )
    zero_positive = [item.rule_id for item in ctx.supports if item.positives == 0]
    lines.append("")
    if zero_positive:
        lines.append(
            "Rules with no expected FAIL at all — their precision is undefined and is reported "
            "as null, never as 100%: " + ", ".join(zero_positive) + "."
        )
    else:
        lines.append(
            "Every rule has at least one expected FAIL on this split, so no per-rule precision "
            "is undefined here; recall for the thinnest rules still rests on single digits of "
            "labels."
        )
    lines.append("")
    lines.append(
        "Read this table together with the labels' own limits. The public labels cannot "
        "discriminate " + "; ".join(UNDISCRIMINATED_EDGES) + "."
    )
    lines.append("")
    lines.append(
        "A rule that passes every public example of such an edge is therefore not evidence that "
        "the edge is implemented correctly — only that this dataset never asked, which is why "
        "the edge-case tests for those rules are written from the rulebook rather than from the "
        "gold labels."
    )
    return lines


def _render_ai(ctx: ReportContext) -> list[str]:
    return [
        "This generator scores the deterministic engine. It does **not** score explanation",
        "quality, and no explanation number appears in this report. The pack requires manual 0/1",
        "scoring of the supplied explanation cases (correct finding, correct evidence, correct",
        "rule, appropriate action, honest uncertainty) plus a separate list of unsupported",
        "statements; that scorecard is produced by hand elsewhere and is not reproducible by a",
        "command, so this report does not report it.",
        "",
        "What this report can state about that seam is structural, and it is the pack's adapter",
        "contract (`<pack>/src/llm_adapter.py`): the explanation output carries exactly four keys;",
        "its cited evidence paths must be a subset of the finding's supplied evidence paths; its",
        "cited rule id must equal the finding's rule id; its review flag must equal the finding's",
        "own; and any failure falls back to the deterministic explanation with the fallback",
        "marked. Nothing in the numbers above depends on whether a model answered, and a model",
        "failure can never change a rule status — the statuses scored here are the deterministic",
        "ones.",
    ]


def _render_security(ctx: ReportContext) -> list[str]:
    return [
        "Synthetic data only; no real patient record, payer rule or adjudication outcome is",
        "present. This report is a read-only artefact: the generator writes the report, its",
        "machine-readable context and the scorer's metrics file, and never writes inside the",
        "mentor pack.",
        "",
        "| Property | Evidence in this run |",
        "|---|---|",
        f"| Pack inputs unmodified | {_manifest_summary(ctx)} |",
        f"| Original claim envelopes preserved | predictions are a separate file "
        f"(`{ctx.predictions.display if ctx.predictions else 'n/a'}`); no input was rewritten |",
        "| No approval, denial, pricing or payment | the result contract has no approval or "
        "denial field; every status is one of the five review outcomes |",
        "| Untrusted text treated as data | attachment text and `notes` never carry instructions; "
        "the deterministic engine scores them as values |",
        "",
        "Audit, review and access-boundary evidence is produced by those workstreams and is not",
        "re-derived here.",
    ]


def _manifest_summary(ctx: ReportContext) -> str:
    if ctx.dataset is None:
        return "not recorded"
    checked = [item for item in ctx.dataset.inputs if item.manifest_agrees is not None]
    matched = [item for item in checked if item.manifest_agrees]
    return (
        f"{len(matched)} of {len(checked)} file digests agree with the pack's own "
        "`SHA256SUMS.json`; the rest are not listed there"
    )


def _render_honesty(ctx: ReportContext) -> list[str]:
    lines = [
        "These are the pack's honesty rules, restated for this run. They are part of the report,",
        "not a footnote:",
        "",
    ]
    for label, text in honesty_statements(ctx):
        lines.append(f"- **{label}.** {text}")
    return lines


def render_report(ctx: ReportContext) -> str:
    """Render the versioned Markdown report from a fully-populated context."""
    if not ctx.split:
        raise ReportError("a report needs a split name")
    if not ctx.metrics:
        raise ReportError(
            "a report needs the mentor scorer's metrics (a rejected run is not a result)"
        )
    overall = _overall(ctx)
    title = f"# ClaimGuard AI — evaluation report ({ctx.split} split)"
    lines: list[str] = [
        title,
        "",
        f"Report format version **{ctx.report_format_version}** · generated {ctx.generated_at} · "
        f"generator `{GENERATOR_DISPLAY}` · engine revision "
        f"`{ctx.engine.git_revision if ctx.engine else 'n/a'}`",
        "",
        f"Headline: {fmt_int(overall.get('count'))} claim-rule pairs, status accuracy "
        f"{fmt_ratio(overall.get('status_accuracy'))}, issue precision "
        f"{fmt_ratio(overall.get('issue_precision'))}, issue recall "
        f"{fmt_ratio(overall.get('issue_recall'))}, false alarms {fmt_int(overall.get('fp'))}, "
        f"missed issues {fmt_int(overall.get('fn'))}.",
        "",
        "Every number below was produced by this single run; none is estimated. A metric with an",
        "empty denominator is printed as `null`, never as 100%.",
        "",
    ]
    sections: tuple[tuple[str, list[str]], ...] = (
        ("## Reproduction", _render_reproduction(ctx)),
        ("## Data discipline and dataset identity", _render_data_discipline(ctx)),
        ("## Engine and catalogue identity", _render_identity(ctx)),
        ("## Scorer verdict and gates", _render_verdict(ctx)),
        ("## Metrics", _render_metrics(ctx)),
        ("## Error analysis", _render_error_analysis(ctx)),
        ("## AI explanation evaluation", _render_ai(ctx)),
        ("## Human review and security", _render_security(ctx)),
        ("## Honesty rules and limitations", _render_honesty(ctx)),
    )
    for heading, body in sections:
        lines.append(heading)
        lines.append("")
        lines.extend(body)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------------------
# Context construction
# ---------------------------------------------------------------------------------------


def build_context(
    *,
    pack_root: Path,
    split: str,
    workdir: Path,
    pred: Path | None,
    rules_dir: Path,
    python: str,
    min_accuracy: float,
    accuracy_scope: str,
    timeout: float,
    baseline: bool,
    max_errors: int,
    command_line: str,
) -> ReportContext:
    """Run the engine (unless ``--pred`` was given), score it twice, and gather the report data."""
    claims_path = pack_root / "data" / split / "claims.jsonl"
    gold_path = pack_root / "data" / split / "expected_results.jsonl"
    for path in (claims_path, gold_path):
        if not path.is_file():
            raise ReportError(f"pack data missing for split {split!r}: {path}")

    engine_run: EngineRun | None = None
    if pred is None:
        pred = workdir / split / "predictions.jsonl"
        engine_run = run_engine(
            python=python,
            claims=claims_path,
            rules_dir=rules_dir,
            output=pred,
            timeout=timeout,
        )
        if engine_run.exit_code != 0:
            raise ReportError(
                f"the engine exited {engine_run.exit_code} and did not produce a complete "
                f"prediction file; refusing to report. Engine stderr:\n{engine_run.stderr.strip()}"
            )
        source = "produced by the engine CLI (`python -m claimguard.edu.run`)"
    else:
        if not pred.is_file():
            raise ReportError(f"predictions file not found: {pred}")
        source = "supplied with `--pred`"

    report = score_predictions(
        pack_root=pack_root,
        split=split,
        pred=pred,
        python=python,
        workdir=workdir,
        min_accuracy=min_accuracy,
        accuracy_scope=accuracy_scope,
        timeout=timeout,
    )
    if not report.scorer.accepted:
        raise ReportError(
            "the mentor's scorer REJECTED these predictions "
            f"(exit {report.scorer.exit_code}); a rejected run is not a result, so no report was "
            f"written. Scorer output:\n{report.scorer.message()}"
        )
    if not isinstance(report.metrics, dict):
        raise ReportError("the scorer accepted the file but its metrics JSON is missing")

    gold_rows = load_jsonl(gold_path)
    pred_rows = load_jsonl(pred)
    all_mismatches = collect_mismatches(gold_rows, pred_rows, -1)
    mismatches = tuple(all_mismatches[:max_errors]) if max_errors >= 0 else all_mismatches
    counts = category_counts(all_mismatches)
    problems = cross_check_categories(counts, as_mapping(report.metrics.get("overall")))
    if problems:
        raise ReportError(
            "the enumerated error categories disagree with the oracle's own aggregates: "
            + "; ".join(problems)
        )

    engine = engine_identity(REPO_ROOT, rules_dir)
    baseline_summary: BaselineSummary | None = None
    baseline_error = ""
    if baseline:
        try:
            baseline_summary = run_baseline_ablation(
                pack_root=pack_root,
                split=split,
                python=python,
                workdir=workdir,
                timeout=timeout,
                max_errors=max_errors,
            )
        except ReportError as exc:
            baseline_error = str(exc)
    context = ReportContext(
        split=split,
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        command_line=command_line,
        engine_run=engine_run,
        predictions=file_identity(pred, "predictions", display=pred.as_posix()),
        predictions_source=source,
        dataset=dataset_identity(pack_root, split),
        engine=engine,
        scorer_command=tuple(report.scorer.command),
        scorer_exit_code=report.scorer.exit_code,
        scorer_message=report.scorer.message(),
        metrics_path=str(report.scorer.metrics_path),
        context_path=str(workdir / split / "report_context.json"),
        metrics=report.metrics,
        independent=report.independent.payload(),
        audit=report.audit.payload(),
        gate={
            "scope": accuracy_scope,
            "min_accuracy": min_accuracy,
            "accuracy": report.gate_accuracy,
            "passed": report.gate_passed,
        },
        failure_reasons=tuple(report.failure_reasons),
        supports=support_analysis(gold_rows, engine.catalogue),
        mismatches=mismatches,
        mismatches_total=len(all_mismatches),
        category_counts=counts,
        claims=report.independent.claims,
        results=report.independent.results,
        baseline=baseline_summary,
        baseline_error=baseline_error,
        max_errors=max_errors,
    )
    write_json(workdir / split / "conformance.json", report.payload())
    write_json(Path(context.context_path), context.payload())
    return context


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="edu_report",
        description=(
            "Run the engine over one mentor-pack split, score it with the mentor's strict "
            "scorer and our conformance harness, and write the versioned evaluation report."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--split", choices=list(SPLITS), default="development")
    parser.add_argument("--output", required=True, help="destination Markdown report")
    parser.add_argument(
        "--pred",
        default=None,
        help="score an existing predictions file instead of running the engine",
    )
    parser.add_argument(
        "--pack-root",
        default=None,
        help="mentor pack root (default: auto-discover, or CLAIMGUARD_PACK_ROOT)",
    )
    parser.add_argument(
        "--rules-dir", default=None, help="rule catalogue directory (default: <pack>/rules)"
    )
    parser.add_argument(
        "--workdir",
        default=DEFAULT_WORKDIR,
        help="where predictions, metrics and the machine-readable context are written",
    )
    parser.add_argument("--python", default=sys.executable, help="interpreter for subprocesses")
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=1.0,
        help="accuracy gate applied by the harness; a negative value disables it",
    )
    parser.add_argument("--accuracy-scope", choices=["implemented", "total"], default="implemented")
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_SCORER_TIMEOUT, help="seconds per subprocess"
    )
    parser.add_argument(
        "--baseline",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "also score the pack's own baseline for the reference comparison (the pack's "
            "evaluation template asks for it); --no-baseline skips it"
        ),
    )
    parser.add_argument(
        "--max-errors", type=int, default=25, help="disagreements listed in the error analysis"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        pack_root = find_pack_root(Path(args.pack_root) if args.pack_root else None)
    except ConformanceError as exc:
        _emit(f"report error: {exc}")
        return EXIT_REFUSED
    rules_dir = Path(args.rules_dir) if args.rules_dir else pack_root / "rules"
    workdir = Path(args.workdir)
    output = Path(args.output)
    # The report quotes what the operator actually typed, defaults included or not.
    command_line = " ".join(argv) if argv is not None else " ".join(sys.argv[1:])

    try:
        context = build_context(
            pack_root=pack_root,
            split=args.split,
            workdir=workdir,
            pred=Path(args.pred) if args.pred else None,
            rules_dir=rules_dir,
            python=args.python,
            min_accuracy=args.min_accuracy,
            accuracy_scope=args.accuracy_scope,
            timeout=args.timeout,
            baseline=args.baseline,
            max_errors=args.max_errors,
            command_line=command_line,
        )
    except ReportError as exc:
        _emit(f"REFUSED: {exc}")
        return EXIT_REFUSED

    report_text = render_report(context)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report_text, encoding="utf-8")

    overall = as_mapping(context.metrics.get("overall"))
    _emit(f"split            : {args.split}")
    _emit(f"predictions      : {context.predictions.display if context.predictions else 'n/a'}")
    _emit(f"metrics (oracle) : {context.metrics_path}")
    _emit(f"context          : {context.context_path}")
    _emit(f"report           : {output} ({len(report_text.splitlines())} lines)")
    _emit("")
    _emit("headline metrics (mentor's strict scorer)")
    for name in (
        "count",
        "tp",
        "fp",
        "fn",
        "tn",
        "issue_precision",
        "issue_recall",
        "issue_f1",
        "false_alarm_rate",
        "status_accuracy",
        "not_implemented",
        "false_abstentions",
        "missed_abstentions",
    ):
        value = overall.get(name)
        rendered = fmt_int(value) if type(value) is int else fmt_ratio(value)
        _emit(f"  {name:<22} {rendered}")
    _emit(
        f"  {'claim_exact_match':<22} "
        f"{fmt_int(context.metrics.get('claims_with_all_statuses_correct'))} / {context.claims}"
    )
    _emit("")
    if context.failure_reasons:
        _emit(f"NON-CONFORMANT ({len(context.failure_reasons)} reason(s)) — the report says so")
        for reason in context.failure_reasons:
            _emit(f"  - {reason.splitlines()[0]}")
        return EXIT_NON_CONFORMANT
    _emit("CONFORMANT: oracle accepted, independent checks found nothing, gate passed")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
