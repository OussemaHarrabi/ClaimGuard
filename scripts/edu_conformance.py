"""Independent conformance harness for the ClaimGuardAI mentor pack's strict oracle.

Two opinions, deliberately kept separate:

1. **The mentor's oracle** (``<pack>/src/evaluate.py``) is executed as a subprocess over
   ``data/<split>/{claims,expected_results}.jsonl`` against a predictions file. It is the
   authority: a non-zero exit means the predictions are inadmissible and its message is
   surfaced verbatim.
2. **An independent re-implementation** of the admissibility contract (this module, no pack
   import) re-checks result shape, literals, review flags, line-id and evidence bounds, and
   re-resolves every evidence JSON pointer against the *original* claim. It also recomputes
   the headline metrics from gold+predictions and cross-checks them against the oracle's
   JSON, so a stale or mismatched metrics file cannot pass unnoticed.

Exit code is 0 only when the oracle accepts, the independent checks find nothing, and the
accuracy gate passes. The gate metric defaults to *implemented accuracy*: exact status
agreement over the claim-rule pairs the predictor actually committed to (pred status !=
NOT_IMPLEMENTED), because the oracle counts NOT_IMPLEMENTED as wrong by design and the pack's
own accepted baseline therefore sits at status_accuracy 0.2 with 4800 NOT_IMPLEMENTED. Use
``--accuracy-scope total`` to gate on the oracle's raw status_accuracy instead.

Usage (from the repository root)::

    uv run python scripts/edu_conformance.py --pred <predictions.jsonl> --split development
    uv run python scripts/edu_conformance.py --pred '<dir>/{split}.jsonl' --all

The pack is read-only; nothing here writes inside it. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

# ---------------------------------------------------------------------------------------
# Frozen contract (docs/07_Evaluation_and_Acceptance.md, schemas/result.schema.json,
# docs/04_Rulebook.md). Restated here on purpose: the harness must not import pack code.
# ---------------------------------------------------------------------------------------

RULE_IDS: tuple[str, ...] = tuple(f"R{i:03d}" for i in range(1, 16))
RESULT_KEYS: set[str] = set(
    {
        "claim_id",
        "rule_id",
        "rule_version",
        "status",
        "severity",
        "affected_line_ids",
        "evidence",
        "rule_source",
        "explanation",
        "corrective_action",
        "confidence",
        "confidence_kind",
        "requires_human_review",
        "method",
        "review_status",
    }
)
STATUSES: set[str] = {"PASS", "FAIL", "UNABLE_TO_ASSESS", "NOT_APPLICABLE", "NOT_IMPLEMENTED"}
REVIEW_STATUSES: set[str] = {"FAIL", "UNABLE_TO_ASSESS"}
SEVERITIES: set[str] = {"high", "medium", "low"}
SPLITS: tuple[str, ...] = ("development", "validation", "stress")
RULE_VERSION = "1.0.0"
RULE_SOURCE_TEMPLATE = "fictional-rulebook/{rule_id}@1.0.0"
METHOD = "deterministic"
REVIEW_STATUS = "unreviewed"
CONFIDENCE_KIND = "not_probabilistic"
ENVELOPE_KEYS: set[str] = set(
    {
        "schema_version",
        "claim_id",
        "invoice_number",
        "patient_id",
        "member_id",
        "provider_id",
        "payer_id",
        "policy_id",
        "diagnosis_code",
        "submission_date",
        "currency",
        "total_amount",
        "coverage",
        "lines",
        "authorizations",
        "attachments",
        "notes",
    }
)
MAX_PROBLEMS_PRINTED = 25
DEFAULT_TIMEOUT_SECONDS = 900.0
PACK_DIR_NAMES: tuple[str, ...] = (
    "ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack",
    "ClaimGuardAI_Student_Starter_Pack",
)


class ConformanceError(RuntimeError):
    """Raised when the harness itself cannot reach a verdict (bad usage, unreadable data)."""


def as_mapping(value: Any) -> Any:
    """A decoded-JSON value narrowed to an object map; anything else is an empty map.

    Decoded JSON is dynamically typed by nature. These two narrowers keep that dynamic view
    (typing them as concrete containers would surface `Unknown` element types everywhere).
    """
    if not isinstance(value, dict):
        return {}
    return cast("Any", value)


def as_list(value: Any) -> Any:
    """A decoded-JSON value narrowed to a list; anything else is an empty list."""
    if not isinstance(value, list):
        return []
    return cast("Any", value)


# ---------------------------------------------------------------------------------------
# JSON helpers (independent of the pack: the pack's own pointer() is not reused)
# ---------------------------------------------------------------------------------------


class PointerError(ValueError):
    """A JSON pointer that does not resolve against the supplied document."""


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON pointer. Raises PointerError when it does not resolve."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise PointerError(f"{pointer!r} is not a JSON pointer (must start with '/')")
    current: Any = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            items = as_list(current)
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise PointerError(f"{pointer!r}: {token!r} is not a list index")
            index = int(token)
            if index >= len(items):
                raise PointerError(f"{pointer!r}: list index {index} out of range")
            current = items[index]
        elif isinstance(current, dict):
            mapping = as_mapping(current)
            if token not in mapping:
                raise PointerError(f"{pointer!r}: key {token!r} absent")
            current = mapping[token]
        else:
            raise PointerError(f"{pointer!r}: cannot descend into {type(current).__name__}")
    return current


def json_equal(left: Any, right: Any) -> bool:
    """Exact JSON equality: booleans are not numbers, numbers compare exactly."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except InvalidOperation:  # pragma: no cover - json.loads cannot produce this
            return False
    if isinstance(left, dict) and isinstance(right, dict):
        left_map = as_mapping(left)
        right_map = as_mapping(right)
        return set(left_map) == set(right_map) and all(
            json_equal(left_map[key], right_map[key]) for key in left_map
        )
    if isinstance(left, list) and isinstance(right, list):
        left_items = as_list(left)
        right_items = as_list(right)
        return len(left_items) == len(right_items) and all(
            json_equal(a, b) for a, b in zip(left_items, right_items, strict=True)
        )
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    return left is None and right is None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file, demanding one JSON object per non-empty line."""
    if not path.is_file():
        raise ConformanceError(f"file not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                parsed: Any = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ConformanceError(f"{path}:{number}: invalid JSON ({exc})") from exc
            if not isinstance(parsed, dict):
                raise ConformanceError(f"{path}:{number}: expected a JSON object")
            rows.append(as_mapping(parsed))
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _emit(text: str = "") -> None:
    sys.stdout.write(text + "\n")


# ---------------------------------------------------------------------------------------
# Pack discovery and oracle invocation
# ---------------------------------------------------------------------------------------


def looks_like_pack(path: Path) -> bool:
    return (
        (path / "src" / "evaluate.py").is_file()
        and (path / "src" / "engine_core.py").is_file()
        and (path / "rules" / "rules.json").is_file()
        and (path / "data" / "development" / "claims.jsonl").is_file()
    )


def find_pack_root(explicit: Path | None = None) -> Path:
    """Locate the read-only mentor pack (explicit flag, env var, then directory search)."""
    if explicit is not None:
        if looks_like_pack(explicit):
            return explicit.resolve()
        raise ConformanceError(f"--pack-root does not look like the mentor pack: {explicit}")
    candidates: list[Path] = []
    env_value = os.environ.get("CLAIMGUARD_PACK_ROOT")
    if env_value:
        candidates.append(Path(env_value))
    for parent in Path(__file__).resolve().parents:
        for name in PACK_DIR_NAMES:
            candidates.append(parent / name)
        candidates.append(parent)
    for candidate in candidates:
        if candidate.is_dir() and looks_like_pack(candidate):
            return candidate.resolve()
    searched = "\n  ".join(str(c) for c in candidates[:12])
    raise ConformanceError(
        f"mentor pack not found; pass --pack-root or set CLAIMGUARD_PACK_ROOT. Searched:\n  "
        f"{searched}"
    )


@dataclass(frozen=True)
class ScorerRun:
    """Outcome of one oracle subprocess call."""

    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    metrics_path: Path

    @property
    def accepted(self) -> bool:
        return self.exit_code == 0

    def message(self) -> str:
        """The oracle's own words: rejection reason on failure, overall metrics on success."""
        parts = [part.strip() for part in (self.stderr, self.stdout) if part.strip()]
        return "\n".join(parts) if parts else f"no output (exit {self.exit_code})"

    def payload(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "exit_code": self.exit_code,
            "metrics_path": str(self.metrics_path),
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def run_scorer(
    *,
    python: str,
    pack_root: Path,
    split: str,
    pred: Path,
    metrics_path: Path,
    timeout: float,
) -> ScorerRun:
    """Run ``<pack>/src/evaluate.py`` exactly as documented in docs/07."""
    command = [
        python,
        str(pack_root / "src" / "evaluate.py"),
        "--gold",
        str(pack_root / "data" / split / "expected_results.jsonl"),
        "--pred",
        str(pred),
        "--claims",
        str(pack_root / "data" / split / "claims.jsonl"),
        "--output",
        str(metrics_path),
    ]
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
    except subprocess.TimeoutExpired as exc:
        raise ConformanceError(
            f"mentor scorer timed out after {timeout:g}s: {' '.join(command)}"
        ) from exc
    return ScorerRun(
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        metrics_path=metrics_path,
    )


# ---------------------------------------------------------------------------------------
# Independent admissibility checks
# ---------------------------------------------------------------------------------------


@dataclass
class IndependentReport:
    """Second opinion: what this harness can prove without the pack's scorer."""

    results: int = 0
    claims: int = 0
    evidence_pointers: int = 0
    problems: list[str] = field(default_factory=list[str])

    @property
    def ok(self) -> bool:
        return not self.problems

    def payload(self) -> dict[str, Any]:
        return {
            "results": self.results,
            "claims": self.claims,
            "evidence_pointers": self.evidence_pointers,
            "problems": list(self.problems),
            "ok": self.ok,
        }


def _claim_line_ids(claim: dict[str, Any]) -> set[str]:
    line_ids: set[str] = set()
    for line in as_list(claim.get("lines")):
        line_id = as_mapping(line).get("line_id")
        if isinstance(line_id, str):
            line_ids.add(line_id)
    return line_ids


def independent_check(
    pred_rows: Sequence[dict[str, Any]],
    claims_rows: Sequence[dict[str, Any]],
) -> IndependentReport:
    """Re-implement the admissibility contract without importing pack code."""
    report = IndependentReport()
    problems = report.problems

    claims: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(claims_rows, 1):
        claim_id = row.get("claim_id")
        if set(row) != ENVELOPE_KEYS:
            problems.append(
                f"claims line {index}: envelope keys differ from the frozen 17-key contract"
            )
        if not isinstance(claim_id, str) or not claim_id:
            problems.append(f"claims line {index}: claim_id must be a non-empty string")
            continue
        if claim_id in claims:
            problems.append(f"claims line {index}: duplicate claim_id {claim_id!r}")
            continue
        claims[claim_id] = row
    report.claims = len(claims)

    seen: set[tuple[str, str]] = set()
    rules_seen: dict[str, set[str]] = {}
    for index, row in enumerate(pred_rows, 1):
        where = f"result line {index}"
        report.results += 1
        if set(row) != RESULT_KEYS:
            missing = sorted(RESULT_KEYS - set(row))
            extra = sorted(set(row) - RESULT_KEYS)
            problems.append(
                f"{where}: result keys must be the exact 15-key set "
                f"(missing={missing}, extra={extra})"
            )
        claim_id = row.get("claim_id")
        rule_id = row.get("rule_id")
        if not isinstance(claim_id, str) or not claim_id:
            problems.append(f"{where}: claim_id must be a non-empty string")
            claim_id = None
        if not isinstance(rule_id, str) or rule_id not in RULE_IDS:
            problems.append(f"{where}: rule_id must be one of R001..R015 (got {rule_id!r})")
            rule_id = None
        if claim_id is not None:
            if rule_id is not None:
                pair = (claim_id, rule_id)
                if pair in seen:
                    problems.append(f"{where}: duplicate result for {claim_id!r}/{rule_id}")
                seen.add(pair)
                rules_seen.setdefault(claim_id, set()).add(rule_id)
            if claim_id not in claims:
                problems.append(f"{where}: result for unknown claim {claim_id!r}")

        status = row.get("status")
        if status not in STATUSES:
            problems.append(f"{where}: status must be one of {sorted(STATUSES)} (got {status!r})")
        severity = row.get("severity")
        if severity not in SEVERITIES:
            problems.append(
                f"{where}: severity must be one of {sorted(SEVERITIES)} (got {severity!r})"
            )
        if row.get("rule_version") != RULE_VERSION:
            problems.append(
                f"{where}: rule_version must be {RULE_VERSION!r} (got {row.get('rule_version')!r})"
            )
        expected_source = RULE_SOURCE_TEMPLATE.format(rule_id=rule_id or "<invalid>")
        if row.get("rule_source") != expected_source:
            problems.append(
                f"{where}: rule_source must be {expected_source!r} (got {row.get('rule_source')!r})"
            )
        if row.get("method") != METHOD:
            problems.append(f"{where}: method must be {METHOD!r} (got {row.get('method')!r})")
        if row.get("review_status") != REVIEW_STATUS:
            problems.append(
                f"{where}: review_status must be {REVIEW_STATUS!r} "
                f"(got {row.get('review_status')!r})"
            )
        explanation = row.get("explanation")
        if not isinstance(explanation, str) or not explanation.strip():
            problems.append(f"{where}: explanation must be a non-empty string")

        confidence = row.get("confidence")
        if confidence is not None:
            problems.append(
                f"{where}: confidence must be null for a deterministic check (got {confidence!r})"
            )
        if row.get("confidence_kind") != CONFIDENCE_KIND:
            problems.append(
                f"{where}: confidence_kind must be {CONFIDENCE_KIND!r} "
                f"(got {row.get('confidence_kind')!r})"
            )
        review_flag = row.get("requires_human_review")
        corrective = row.get("corrective_action")
        if status in REVIEW_STATUSES:
            if review_flag is not True:
                problems.append(f"{where}: requires_human_review must be true for {status}")
            if not isinstance(corrective, str) or not corrective.strip():
                problems.append(f"{where}: corrective_action must be non-empty for {status}")
        else:
            if not isinstance(review_flag, bool):
                problems.append(f"{where}: requires_human_review must be a boolean")
            if not isinstance(corrective, str):
                problems.append(f"{where}: corrective_action must be a string")

        claim = claims.get(claim_id) if claim_id is not None else None
        raw_affected = row.get("affected_line_ids")
        affected = as_list(raw_affected)
        if not isinstance(raw_affected, list) or not all(
            isinstance(item, str) for item in affected
        ):
            problems.append(f"{where}: affected_line_ids must be a list of strings")
        elif claim is not None:
            unknown = sorted(set(affected) - _claim_line_ids(claim))
            if unknown:
                problems.append(f"{where}: affected_line_ids absent from the claim: {unknown}")

        raw_evidence = row.get("evidence")
        evidence = as_list(raw_evidence)
        if not isinstance(raw_evidence, list):
            problems.append(f"{where}: evidence must be a list")
        if status != "NOT_IMPLEMENTED" and not evidence:
            problems.append(f"{where}: evidence must be non-empty for status {status}")
        for entry in evidence:
            entry_map = as_mapping(entry)
            if not isinstance(entry, dict) or set(entry_map) != {"path", "value"}:
                problems.append(
                    f"{where}: each evidence entry needs exactly {{'path','value'}} (got {entry!r})"
                )
                continue
            pointer = entry_map["path"]
            if not isinstance(pointer, str) or not pointer.startswith("/"):
                problems.append(
                    f"{where}: evidence path must be a JSON pointer starting with '/' "
                    f"(got {pointer!r})"
                )
                continue
            report.evidence_pointers += 1
            if claim is None:
                continue
            try:
                actual = resolve_pointer(claim, pointer)
            except PointerError as exc:
                problems.append(f"{where}: evidence pointer does not resolve: {exc}")
                continue
            if not json_equal(actual, entry_map["value"]):
                problems.append(
                    f"{where}: evidence value mismatch at {pointer}: claim holds {actual!r}, "
                    f"prediction claims {entry_map['value']!r}"
                )

    for claim_id in sorted(claims):
        missing = sorted(set(RULE_IDS) - rules_seen.get(claim_id, set()))
        if missing:
            problems.append(f"claim {claim_id}: missing results for {missing}")
    for claim_id in sorted(set(rules_seen) - set(claims)):
        problems.append(f"predictions contain results for unknown claim {claim_id!r}")

    return report


# ---------------------------------------------------------------------------------------
# Metrics: taken from the oracle, cross-checked by the harness
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PredictionAudit:
    """Metrics recomputed by the harness from gold+predictions (independent arithmetic)."""

    pairs: int
    implemented_pairs: int
    implemented_accuracy: float | None
    status_accuracy: float | None
    not_implemented: int
    tp: int
    fp: int
    fn: int

    def payload(self) -> dict[str, Any]:
        return {
            "pairs": self.pairs,
            "implemented_pairs": self.implemented_pairs,
            "implemented_accuracy": self.implemented_accuracy,
            "status_accuracy": self.status_accuracy,
            "not_implemented": self.not_implemented,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
        }


def _index_by_pair(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        claim_id = row.get("claim_id")
        rule_id = row.get("rule_id")
        if isinstance(claim_id, str) and isinstance(rule_id, str):
            indexed.setdefault((claim_id, rule_id), row)
    return indexed


def audit_predictions(
    gold_rows: Sequence[dict[str, Any]],
    pred_rows: Sequence[dict[str, Any]],
) -> PredictionAudit:
    """Recompute the oracle's headline metrics, plus implemented-only accuracy."""
    gold = _index_by_pair(gold_rows)
    pred = _index_by_pair(pred_rows)
    keys = sorted(set(gold) & set(pred))
    tp = fp = fn = correct = committed = correct_committed = not_implemented = 0
    for key in keys:
        gold_status = gold[key].get("status")
        pred_status = pred[key].get("status")
        if pred_status == "FAIL" and gold_status == "FAIL":
            tp += 1
        elif pred_status == "FAIL":
            fp += 1
        elif gold_status == "FAIL":
            fn += 1
        if gold_status == pred_status:
            correct += 1
        if pred_status == "NOT_IMPLEMENTED":
            not_implemented += 1
        else:
            committed += 1
            if gold_status == pred_status:
                correct_committed += 1
    return PredictionAudit(
        pairs=len(keys),
        implemented_pairs=committed,
        implemented_accuracy=(correct_committed / committed) if committed else None,
        status_accuracy=(correct / len(keys)) if keys else None,
        not_implemented=not_implemented,
        tp=tp,
        fp=fp,
        fn=fn,
    )


def cross_check_metrics(
    metrics: dict[str, Any], audit: PredictionAudit, problems: list[str]
) -> None:
    """The oracle's JSON must describe the very file we handed it."""
    overall = as_mapping(metrics.get("overall"))
    if not overall:
        problems.append("oracle metrics JSON has no 'overall' object")
        return
    expected: dict[str, Any] = {
        "count": audit.pairs,
        "tp": audit.tp,
        "fp": audit.fp,
        "fn": audit.fn,
        "status_accuracy": audit.status_accuracy,
        "not_implemented": audit.not_implemented,
    }
    for name, want in expected.items():
        got = overall.get(name)
        if isinstance(want, float) or isinstance(got, float):
            matches = (
                isinstance(got, (int, float))
                and isinstance(want, (int, float))
                and abs(float(got) - float(want)) < 1e-12
            )
        else:
            matches = got == want
        if not matches:
            problems.append(
                f"oracle metric {name!r}={got!r} disagrees with the independent "
                f"recomputation {want!r}"
            )


# ---------------------------------------------------------------------------------------
# Split orchestration and reporting
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SplitRequest:
    """Everything one conformance run over one pack split needs."""

    split: str
    pred: Path
    pack_root: Path
    python: str
    workdir: Path
    min_accuracy: float
    accuracy_scope: str
    timeout: float


@dataclass
class SplitReport:
    """Verdict for one split: oracle outcome, independent findings, gate decision."""

    request: SplitRequest
    scorer: ScorerRun
    metrics: dict[str, Any] | None
    independent: IndependentReport
    audit: PredictionAudit
    gate_accuracy: float | None
    gate_passed: bool
    failure_reasons: list[str]

    @property
    def ok(self) -> bool:
        return not self.failure_reasons

    def payload(self) -> dict[str, Any]:
        data_dir = self.request.pack_root / "data" / self.request.split
        return {
            "split": self.request.split,
            "predictions": str(self.request.pred),
            "pack_root": str(self.request.pack_root),
            "gold": str(data_dir / "expected_results.jsonl"),
            "claims": str(data_dir / "claims.jsonl"),
            "scorer": self.scorer.payload(),
            "metrics": self.metrics,
            "independent": self.independent.payload(),
            "independent_audit": self.audit.payload(),
            "gate": {
                "scope": self.request.accuracy_scope,
                "min_accuracy": self.request.min_accuracy,
                "accuracy": self.gate_accuracy,
                "passed": self.gate_passed,
            },
            "conformant": self.ok,
            "failure_reasons": list(self.failure_reasons),
        }


def run_split(request: SplitRequest) -> SplitReport:
    """Score one split with the oracle, then audit the same predictions independently."""
    failure_reasons: list[str] = []
    data_dir = request.pack_root / "data" / request.split
    gold_path = data_dir / "expected_results.jsonl"
    claims_path = data_dir / "claims.jsonl"
    for path in (gold_path, claims_path):
        if not path.is_file():
            raise ConformanceError(f"pack data missing for split {request.split!r}: {path}")
    if not request.pred.is_file():
        raise ConformanceError(f"predictions file not found: {request.pred}")

    metrics_path = request.workdir / request.split / "metrics.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    scorer = run_scorer(
        python=request.python,
        pack_root=request.pack_root,
        split=request.split,
        pred=request.pred,
        metrics_path=metrics_path,
        timeout=request.timeout,
    )

    metrics: dict[str, Any] | None = None
    if scorer.accepted:
        try:
            loaded: Any = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConformanceError(
                f"oracle exited 0 but its metrics file is unreadable: {metrics_path} ({exc})"
            ) from exc
        if not isinstance(loaded, dict):
            raise ConformanceError(f"oracle metrics file is not an object: {metrics_path}")
        metrics = as_mapping(loaded)
    else:
        failure_reasons.append(
            f"mentor scorer rejected the predictions (exit {scorer.exit_code}): {scorer.message()}"
        )

    independent = independent_check(load_jsonl(request.pred), load_jsonl(claims_path))
    if not independent.ok:
        failure_reasons.append(f"{len(independent.problems)} independent admissibility problem(s)")
    audit = audit_predictions(load_jsonl(gold_path), load_jsonl(request.pred))
    if metrics is not None:
        before = len(independent.problems)
        cross_check_metrics(metrics, audit, independent.problems)
        if len(independent.problems) != before:
            failure_reasons.append(
                f"{len(independent.problems) - before} oracle/metric disagreement(s)"
            )

    gate_passed = True
    gate_accuracy: float | None = None
    if request.min_accuracy >= 0:  # a negative threshold disables the gate
        if request.accuracy_scope == "total":
            gate_accuracy = audit.status_accuracy
        elif audit.implemented_pairs:
            gate_accuracy = audit.implemented_accuracy
        else:
            # Nothing committed at all: silence must not read as conformance.
            gate_accuracy = 0.0
        gate_passed = gate_accuracy is not None and gate_accuracy >= request.min_accuracy
        if not gate_passed:
            failure_reasons.append(
                f"accuracy gate failed: {request.accuracy_scope} accuracy "
                f"{_fmt(gate_accuracy, 6)} < --min-accuracy {request.min_accuracy:g}"
            )

    return SplitReport(
        request=request,
        scorer=scorer,
        metrics=metrics,
        independent=independent,
        audit=audit,
        gate_accuracy=gate_accuracy,
        gate_passed=gate_passed,
        failure_reasons=failure_reasons,
    )


# ---------------------------------------------------------------------------------------
# Human-readable report
# ---------------------------------------------------------------------------------------


def _fmt(value: float | None, digits: int = 4) -> str:
    return "null" if value is None else f"{value:.{digits}f}"


def _fmt_int(value: Any) -> str:
    return str(value) if isinstance(value, int) else "?"


PER_RULE_COLUMNS: tuple[str, ...] = (
    "rule",
    "n",
    "tp",
    "fp",
    "fn",
    "tn",
    "prec",
    "rec",
    "f1",
    "far",
    "acc",
    "ni",
)


def _column_line(cells: Sequence[str]) -> str:
    head = f"  {cells[0]:>8} {cells[1]:>8}"
    return head + " " + " ".join(f"{cell:>7}" for cell in cells[2:])


def _metric_lines(metrics: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    overall = as_mapping(metrics.get("overall"))
    if not overall:
        return ["  unavailable: the oracle metrics JSON has no 'overall' object"]
    rows: tuple[tuple[str, str], ...] = (
        ("claim-rule pairs", _fmt_int(overall.get("count"))),
        ("issue_precision", _fmt(overall.get("issue_precision"))),
        ("issue_recall", _fmt(overall.get("issue_recall"))),
        ("issue_f1", _fmt(overall.get("issue_f1"))),
        ("false_alarm_rate", _fmt(overall.get("false_alarm_rate"))),
        ("status_accuracy", _fmt(overall.get("status_accuracy"))),
        ("not_implemented", _fmt_int(overall.get("not_implemented"))),
        ("false_abstentions", _fmt_int(overall.get("false_abstentions"))),
        ("missed_abstentions", _fmt_int(overall.get("missed_abstentions"))),
        (
            "claims_with_all_statuses_correct",
            _fmt_int(metrics.get("claims_with_all_statuses_correct")),
        ),
        (
            "tp / fp / fn / tn",
            " / ".join(_fmt_int(overall.get(name)) for name in ("tp", "fp", "fn", "tn")),
        ),
    )
    lines.extend(f"  {name:<34}{value}" for name, value in rows)

    by_rule = as_mapping(metrics.get("by_rule"))
    lines.append("")
    lines.append("per-rule")
    lines.append(_column_line(PER_RULE_COLUMNS))
    for rule_id in sorted(by_rule):
        entry = as_mapping(by_rule[rule_id])
        if entry:
            lines.append(
                _column_line(
                    (
                        rule_id,
                        _fmt_int(entry.get("count")),
                        _fmt_int(entry.get("tp")),
                        _fmt_int(entry.get("fp")),
                        _fmt_int(entry.get("fn")),
                        _fmt_int(entry.get("tn")),
                        _fmt(entry.get("issue_precision")),
                        _fmt(entry.get("issue_recall")),
                        _fmt(entry.get("issue_f1")),
                        _fmt(entry.get("false_alarm_rate")),
                        _fmt(entry.get("status_accuracy")),
                        _fmt_int(entry.get("not_implemented")),
                    )
                )
            )

    lines.append("")
    lines.append("confusion (expected -> predicted)")
    for item in as_list(metrics.get("confusion")):
        item_map = as_mapping(item)
        expected = str(item_map.get("expected"))
        predicted = str(item_map.get("predicted"))
        lines.append(f"  {expected:>16} -> {predicted:<16} {_fmt_int(item_map.get('count'))}")
    return lines


def format_report(report: SplitReport) -> str:
    request = report.request
    lines: list[str] = [
        f"=== ClaimGuardAI mentor-pack conformance: {request.split} ===",
        f"predictions : {request.pred}",
        f"pack root   : {request.pack_root}",
        f"oracle      : exit {report.scorer.exit_code} ({' '.join(report.scorer.command)})",
    ]
    if report.scorer.accepted:
        lines.append(f"oracle json : {report.scorer.metrics_path}")
    else:
        lines.append("oracle says :")
        lines.extend(f"  {line}" for line in report.scorer.message().splitlines())

    lines.append("")
    lines.append("metrics from the mentor oracle (claim-rule level)")
    if isinstance(report.metrics, dict):
        lines.extend(_metric_lines(report.metrics))
    else:
        lines.append("  unavailable: the oracle did not accept the predictions")

    audit = report.audit
    lines.append("")
    lines.append("independent checks (this harness; no pack code imported)")
    lines.append(f"  results                            {audit.pairs}")
    lines.append(f"  claims                             {report.independent.claims}")
    lines.append(
        f"  evidence pointers                  {report.independent.evidence_pointers} "
        f"re-resolved against the original claims"
    )
    lines.append(f"  status_accuracy (recomputed)       {_fmt(audit.status_accuracy)}")
    lines.append(
        f"  implemented_accuracy               {_fmt(audit.implemented_accuracy)} "
        f"over {audit.implemented_pairs} committed pair(s)"
    )
    lines.append(f"  problems                           {len(report.independent.problems)}")
    for problem in report.independent.problems[:MAX_PROBLEMS_PRINTED]:
        lines.append(f"    - {problem}")
    if len(report.independent.problems) > MAX_PROBLEMS_PRINTED:
        lines.append(
            f"    ... {len(report.independent.problems) - MAX_PROBLEMS_PRINTED} more "
            f"(see the report JSON)"
        )

    lines.append("")
    lines.append(
        f"accuracy gate: scope={request.accuracy_scope} "
        f"min_accuracy={request.min_accuracy:g} accuracy={_fmt(report.gate_accuracy)} "
        f"-> {'PASS' if report.gate_passed else 'FAIL'}"
    )
    lines.append("")
    if report.ok:
        lines.append("RESULT: CONFORMANT")
    else:
        lines.append(f"RESULT: NON-CONFORMANT ({len(report.failure_reasons)} reason(s))")
        for reason in report.failure_reasons:
            first, _, rest = reason.partition("\n")
            lines.append(f"  - {first}")
            lines.extend(f"    {line}" for line in rest.splitlines())
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------


def resolve_pred_paths(pred: str, splits: Sequence[str]) -> dict[str, Path]:
    """Map each split to its predictions file ('{split}' placeholder expands per split)."""
    if "{split}" in pred:
        return {split: Path(pred.replace("{split}", split)) for split in splits}
    if len(splits) != 1:
        raise ConformanceError(
            "--all needs one predictions file per split: pass --pred with a '{split}' "
            "placeholder, e.g. 'C:/tmp/out/{split}.jsonl'"
        )
    return {splits[0]: Path(pred)}


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="edu_conformance",
        description=(
            "Verify a predictions file against the mentor pack's strict scorer, plus an "
            "independent re-implementation of its admissibility rules."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--pred",
        required=True,
        help="predictions JSONL; may contain '{split}' when using --all",
    )
    parser.add_argument("--split", choices=list(SPLITS), help="pack split to score against")
    parser.add_argument("--all", action="store_true", help="score every split in turn")
    parser.add_argument(
        "--pack-root",
        default=None,
        help="mentor pack root (default: auto-discover, or CLAIMGUARD_PACK_ROOT)",
    )
    parser.add_argument(
        "--python", default=sys.executable, help="interpreter used to run the pack scorer"
    )
    parser.add_argument(
        "--workdir",
        default=None,
        help="where per-split metrics.json and conformance.json are written",
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=1.0,
        help="minimum accuracy required by the gate; a negative value disables the gate",
    )
    parser.add_argument(
        "--accuracy-scope",
        choices=["implemented", "total"],
        default="implemented",
        help=(
            "'implemented': gate on pairs the predictor committed to (pred status != "
            "NOT_IMPLEMENTED); 'total': gate on the oracle's status_accuracy over all pairs"
        ),
    )
    parser.add_argument(
        "--scorer-timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="seconds allowed for one oracle run",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.all and args.split:
            raise ConformanceError("--all and --split are mutually exclusive")
        if args.all:
            splits: tuple[str, ...] = SPLITS
        elif args.split:
            splits = (args.split,)
        else:
            raise ConformanceError("choose a split with --split <name> or use --all")
        pack_root = find_pack_root(Path(args.pack_root) if args.pack_root else None)
        workdir = (
            Path(args.workdir)
            if args.workdir
            else Path(tempfile.gettempdir()) / "claimguard-edu-conformance"
        )
        pred_paths = resolve_pred_paths(args.pred, splits)
    except ConformanceError as exc:
        _emit(f"harness error: {exc}")
        return 2

    exit_code = 0
    for split in splits:
        request = SplitRequest(
            split=split,
            pred=pred_paths[split],
            pack_root=pack_root,
            python=args.python,
            workdir=workdir,
            min_accuracy=args.min_accuracy,
            accuracy_scope=args.accuracy_scope,
            timeout=args.scorer_timeout,
        )
        try:
            report = run_split(request)
        except ConformanceError as exc:
            _emit(f"harness error [{split}]: {exc}")
            exit_code = 2
            continue
        write_json(workdir / split / "conformance.json", report.payload())
        _emit(format_report(report))
        _emit(f"report: {workdir / split / 'conformance.json'}")
        _emit("")
        if not report.ok:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
