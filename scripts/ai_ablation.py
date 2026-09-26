"""AI assistance ablation over one real split.

Usage (from the repository root)::

    uv run python scripts/ai_ablation.py --split development

What one run does, in order:

1. **Runs the engine** (``python -m claimguard.edu.run``) over the split's claim file and the
   rule catalogue, unless ``--pred`` supplies an existing result file.
2. **Passes every finding through the bounded explanation layer twice**: once with the
   deterministic template provider (the product default) and once with a provider that fails the
   way an unavailable model fails (``UnavailableModelProvider``). For each path it records how
   many findings were served, how many explanations the verifier accepted, how many fell back to
   the deterministic text, how many were declined, and why — grouped by rule and by status.
3. **Compares the two paths' statuses with each other and with the engine's own output.** That
   count is the ablation's headline: the assistance layer may rewrite prose and nothing else, so
   a non-zero count means the layer moved a finding, and the run exits non-zero.

No network is used and the run *proves* it: a socket audit hook is armed for the whole
explanation phase and fails the run the moment a socket is created or resolved (see
:class:`NetworkGuard`). The failing-provider path is the shipped fail-closed provider, which
raises before any transport exists.

Nothing here scores explanation *quality*: the pack requires manual 0/1 scoring of its 25 cases,
and no script can substitute for it (``docs/verification/AI-ABLATION.md`` §5). This ablation
measures what the layer *contributes structurally* and what it costs when a model is missing.

Exit codes: ``0`` no status moved on either path; ``1`` a status moved (the tables say where);
``2`` refused (usage, IO, rule-catalogue, engine or contract failure).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Final

from claimguard.edu.explain import (
    SECURITY_DECISION_ACCEPT,
    SECURITY_DECISION_DECLINE,
    SECURITY_DECISION_FALLBACK,
    ExplanationOutcome,
    ExplanationProvider,
    ModelSettings,
    TemplateExplanationProvider,
    UnavailableModelProvider,
    apply_outcomes,
    explain_records,
    provider_name,
    provider_source_kind,
)
from claimguard.edu.policy import RuleContext, RuleDirError

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from edu_conformance import (  # noqa: E402  (sibling module; sys.path fixed above)
    RULE_IDS,
    SPLITS,
    ConformanceError,
    find_pack_root,
    load_jsonl,
    write_json,
)
from edu_report import (  # noqa: E402  (sibling module; the engine invocation lives there)
    EngineRun,
    ReportError,
    run_engine,
)

DEFAULT_WORKDIR = "artifacts/ai-ablation"
DEFAULT_TIMEOUT = 900.0
MAX_REASONS_PRINTED = 10

EXIT_OK = 0
EXIT_INVARIANCE_VIOLATED = 1
EXIT_REFUSED = 2

#: Result field the layer is allowed to rewrite. Every other field is immutable.
MUTABLE_FIELD: Final = "explanation"

#: Only this field's value is compared for "a status moved".
STATUS_FIELD: Final = "status"

#: Table row order: the five statuses of the frozen contract.
STATUS_ORDER: Final[tuple[str, ...]] = (
    "PASS",
    "FAIL",
    "UNABLE_TO_ASSESS",
    "NOT_APPLICABLE",
    "NOT_IMPLEMENTED",
)

#: Reason text → category, scanned in order. Every needle is a fixed phrase of our own code
#: (``claimguard/edu/explain/verifier.py``, ``provider.py``), so the classification cannot drift
#: silently: ``test_ablation_script.py`` classifies the verifier's real reason strings.
REASON_CATEGORIES: Final[tuple[tuple[str, str], ...]] = (
    ("keys must be exactly", "rejected: schema keys"),
    ("explanation output must be a json object", "rejected: not an object"),
    ("must be a non-empty string", "rejected: empty text"),
    ("asserts an adjudication or clinical conclusion", "rejected: adjudication language"),
    ("attempts an unreviewed action", "rejected: unreviewed action"),
    ("instruction-like content", "rejected: instruction-like content"),
    ("merely repeats the rule text", "rejected: rule echo"),
    ("cited_evidence_paths must be a non-empty list", "rejected: no citations"),
    ("was not supplied with the finding", "rejected: uncited evidence"),
    ("does not resolve in the original envelope", "rejected: unresolvable citation"),
    ("resolves to", "rejected: citation value mismatch"),
    ("envelope belongs to", "rejected: foreign envelope"),
    ("cited_rule_ids must be", "rejected: wrong rule id"),
    ("needs_human_review must", "rejected: review flag invalid"),
    ("no explanation provider is configured", "fallback: provider absent"),
    ("is not sent to a model", "declined: status not model-eligible"),
    ("no evidence pointer to cite", "declined: no citable evidence"),
    (" failed: ", "fallback: provider failure"),
)


class AblationError(RuntimeError):
    """Raised when the ablation cannot be run or its contract is broken."""


class NetworkAttemptedError(RuntimeError):
    """A socket operation was attempted inside an armed :class:`NetworkGuard`."""


# ---------------------------------------------------------------------------------------
# Offline proof: a socket audit hook that fails the run
# ---------------------------------------------------------------------------------------

#: Event logs of the armed guards, innermost last. The hook appends to the innermost one.
_ACTIVE_GUARDS: list[list[str]] = []
#: Single-element flag: the audit hook is installed at most once per process.
_INSTALLED: list[bool] = []


def _audit_hook(event: str, args: tuple[Any, ...]) -> None:
    """Fail the run on any socket event while a guard is armed (a no-op otherwise)."""
    del args
    if not _ACTIVE_GUARDS or not event.startswith("socket."):
        return
    _ACTIVE_GUARDS[-1].append(event)
    raise NetworkAttemptedError(
        f"this ablation is offline by contract, but {event} was attempted while it ran"
    )


def _install_audit_hook() -> None:
    """Install the socket audit hook once per process."""
    if not _INSTALLED:
        sys.addaudithook(_audit_hook)
        _INSTALLED.append(True)


class NetworkGuard:
    """An armed window in which any socket event fails the run: the offline proof.

    CPython raises ``socket.__new__`` when a socket object is constructed and
    ``socket.getaddrinfo`` when a name is resolved, which is everything a transport must do
    before sending a byte. The hook is installed once and does nothing while no guard is armed,
    so importing this module cannot change the behaviour of the process.
    """

    def __init__(self) -> None:
        self.events: list[str] = []

    def __enter__(self) -> NetworkGuard:
        _install_audit_hook()
        _ACTIVE_GUARDS.append(self.events)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        _ACTIVE_GUARDS.remove(self.events)


# ---------------------------------------------------------------------------------------
# Providers under test
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderPath:
    """One provider configuration the whole split is run through."""

    label: str
    expectation: str
    provider: ExplanationProvider

    def payload(self) -> dict[str, str]:
        return {
            "label": self.label,
            "expectation": self.expectation,
            "provider": provider_name(self.provider),
            "source_kind": provider_source_kind(self.provider),
        }


def provider_paths() -> tuple[ProviderPath, ...]:
    """The two paths of the ablation, in report order."""
    return (
        ProviderPath(
            label="template",
            expectation="deterministic template text: always available, no model, no network",
            provider=TemplateExplanationProvider(),
        ),
        ProviderPath(
            label="model-unavailable",
            expectation=(
                "model selected but unreachable: every model-eligible finding falls back to the "
                "deterministic text, every other finding is declined"
            ),
            provider=UnavailableModelProvider(),
        ),
    )


# ---------------------------------------------------------------------------------------
# Tallying
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Counts:
    """How one group of outcomes was decided by the layer's own security decision."""

    served: int = 0
    accepted: int = 0
    fell_back: int = 0
    declined: int = 0
    rewritten: int = 0

    def payload(self) -> dict[str, int]:
        return {
            "served": self.served,
            "accepted": self.accepted,
            "fell_back": self.fell_back,
            "declined": self.declined,
            "rewritten": self.rewritten,
        }


def tally(outcomes: Iterable[ExplanationOutcome]) -> Counts:
    """Count outcomes by decision; an unrecognised decision is a contract break, not a bucket."""
    served = accepted = fell_back = declined = rewritten = 0
    for outcome in outcomes:
        served += 1
        rewritten += 1 if outcome.rewritten else 0
        if outcome.security_decision == SECURITY_DECISION_ACCEPT:
            accepted += 1
        elif outcome.security_decision == SECURITY_DECISION_FALLBACK:
            fell_back += 1
        elif outcome.security_decision == SECURITY_DECISION_DECLINE:
            declined += 1
        else:
            raise AblationError(f"unrecognised security decision {outcome.security_decision!r}")
    return Counts(
        served=served,
        accepted=accepted,
        fell_back=fell_back,
        declined=declined,
        rewritten=rewritten,
    )


def group_counts(
    outcomes: Sequence[ExplanationOutcome], key: Callable[[ExplanationOutcome], str]
) -> dict[str, Counts]:
    """Group outcomes by ``key`` and tally each group, in first-seen order."""
    buckets: dict[str, list[ExplanationOutcome]] = {}
    for outcome in outcomes:
        buckets.setdefault(key(outcome), []).append(outcome)
    return {name: tally(items) for name, items in buckets.items()}


def outcome_reasons(outcome: ExplanationOutcome) -> tuple[str, ...]:
    """Every reason attached to an outcome: rejections, whether fatal or not, and the decline."""
    reasons = list(outcome.rejection_reasons)
    if outcome.declined_reason is not None:
        reasons.append(outcome.declined_reason)
    return tuple(reasons)


def reason_category(reason: str) -> str:
    """The category of one reason text, or ``"other"`` when no known phrase matches."""
    haystack = " ".join(reason.split()).casefold()
    for needle, category in REASON_CATEGORIES:
        if needle in haystack:
            return category
    return "other"


def reason_counts(outcomes: Sequence[ExplanationOutcome]) -> dict[str, int]:
    """Category → number of reasons observed across ``outcomes``."""
    counts: dict[str, int] = {}
    for outcome in outcomes:
        for reason in outcome_reasons(outcome):
            category = reason_category(reason)
            counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def reason_texts(outcomes: Sequence[ExplanationOutcome]) -> dict[str, int]:
    """Exact reason text → number of outcomes carrying it (most frequent first)."""
    counts: dict[str, int] = {}
    for outcome in outcomes:
        for reason in outcome_reasons(outcome):
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


@dataclass(frozen=True)
class PathSummary:
    """What one provider path did with every finding of the split."""

    label: str
    provider: str
    source_kind: str
    expectation: str
    counts: Counts
    by_rule: dict[str, Counts]
    by_status: dict[str, Counts]
    reasons: dict[str, int]
    reason_texts: dict[str, int]

    def payload(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "provider": self.provider,
            "source_kind": self.source_kind,
            "expectation": self.expectation,
            "counts": self.counts.payload(),
            "by_rule": {name: counts.payload() for name, counts in self.by_rule.items()},
            "by_status": {name: counts.payload() for name, counts in self.by_status.items()},
            "reasons": self.reasons,
            "reason_texts": self.reason_texts,
        }


def summarise_path(path: ProviderPath, outcomes: Sequence[ExplanationOutcome]) -> PathSummary:
    """Tally one path's outcomes: overall, by rule, by status, and by reason."""
    return PathSummary(
        label=path.label,
        provider=provider_name(path.provider),
        source_kind=provider_source_kind(path.provider),
        expectation=path.expectation,
        counts=tally(outcomes),
        by_rule=group_counts(outcomes, lambda outcome: outcome.rule_id),
        by_status=group_counts(outcomes, lambda outcome: outcome.status),
        reasons=reason_counts(outcomes),
        reason_texts=reason_texts(outcomes),
    )


# ---------------------------------------------------------------------------------------
# Invariance: did anything but the prose move?
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StatusChange:
    """One finding whose ``status`` differs between two result sets."""

    claim_id: str
    rule_id: str
    left: str
    right: str

    def payload(self) -> dict[str, str]:
        return {
            "claim_id": self.claim_id,
            "rule_id": self.rule_id,
            "left": self.left,
            "right": self.right,
        }


@dataclass(frozen=True)
class RecordChange:
    """One finding where a field other than ``explanation`` differs."""

    claim_id: str
    rule_id: str
    fields: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {"claim_id": self.claim_id, "rule_id": self.rule_id, "fields": list(self.fields)}


def index_records(
    records: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    """``(claim_id, rule_id)`` → record, refusing a duplicate row."""
    index: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in records:
        key = (str(record.get("claim_id")), str(record.get("rule_id")))
        if key in index:
            raise AblationError(f"duplicate result row for {key[0]}/{key[1]}")
        index[key] = record
    return index


def status_changes(
    left: Mapping[tuple[str, str], Mapping[str, Any]],
    right: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[StatusChange]:
    """Findings whose status differs, in row order; different row sets are a contract break."""
    if set(left) != set(right):
        missing = sorted(set(left) - set(right))[:5]
        extra = sorted(set(right) - set(left))[:5]
        raise AblationError(
            f"the two result sets cover different rows: only on the left={missing} "
            f"only on the right={extra}"
        )
    changes: list[StatusChange] = []
    for key in sorted(left):
        before = str(left[key].get(STATUS_FIELD))
        after = str(right[key].get(STATUS_FIELD))
        if before != after:
            changes.append(StatusChange(key[0], key[1], before, after))
    return changes


def immutable_changes(
    left: Sequence[Mapping[str, Any]], right: Sequence[Mapping[str, Any]]
) -> list[RecordChange]:
    """Findings where any field other than ``explanation`` differs (positional pairing)."""
    if len(left) != len(right):
        raise AblationError(
            f"row counts differ: {len(left)} on the left, {len(right)} on the right"
        )
    changes: list[RecordChange] = []
    for before, after in zip(left, right, strict=True):
        fields = tuple(
            sorted(
                key
                for key in set(before) | set(after)
                if key != MUTABLE_FIELD and before.get(key) != after.get(key)
            )
        )
        if fields:
            changes.append(
                RecordChange(
                    claim_id=str(before.get("claim_id")),
                    rule_id=str(before.get("rule_id")),
                    fields=fields,
                )
            )
    return changes


def count_changes(
    changes: Sequence[StatusChange], key: Callable[[StatusChange], str]
) -> dict[str, int]:
    """Number of changes per group name."""
    counts: dict[str, int] = {}
    for change in changes:
        name = key(change)
        counts[name] = counts.get(name, 0) + 1
    return counts


# ---------------------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Inputs:
    """Where the claims and the rule catalogue come from."""

    claims: Path
    rules_dir: Path
    pack_root: Path | None


def resolve_inputs(
    claims: str | None, rules_dir: str | None, pack_root: str | None, split: str
) -> Inputs:
    """Resolve the claim file and rule directory (explicit flags, else the pack)."""
    explicit_pack = Path(pack_root) if pack_root else None
    if claims is not None and rules_dir is not None:
        return Inputs(Path(claims), Path(rules_dir), explicit_pack)
    found = find_pack_root(explicit_pack)
    return Inputs(
        claims=Path(claims) if claims else found / "data" / split / "claims.jsonl",
        rules_dir=Path(rules_dir) if rules_dir else found / "rules",
        pack_root=found,
    )


def group_by_claim(records: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """Claim id → its result records, in file order."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record.get("claim_id")), []).append(record)
    return grouped


@dataclass(frozen=True)
class AblationRun:
    """Everything one ablation run measured."""

    split: str
    generated_at: str
    claims: int
    findings: int
    claims_path: Path
    predictions: Path
    predictions_sha256: str
    engine_command: str
    engine_exit_code: int
    engine_ran: bool
    model_endpoint_configured: bool
    socket_events: tuple[str, ...]
    paths: tuple[PathSummary, ...]
    between_paths: tuple[StatusChange, ...]
    vs_engine: dict[str, tuple[StatusChange, ...]]
    field_changes: dict[str, tuple[RecordChange, ...]]
    changes_by_rule: dict[str, int]
    changes_by_engine_status: dict[str, int]
    claims_with_a_change: int

    @property
    def invariant_ok(self) -> bool:
        """True when no status moved between the paths or from the engine's own output."""
        return not self.between_paths and all(not changes for changes in self.vs_engine.values())

    def payload(self) -> dict[str, Any]:
        """The machine-readable summary of this run."""
        return {
            "schema": "claimguard-ai-ablation/v1",
            "generated_at": self.generated_at,
            "split": self.split,
            "claims": self.claims,
            "findings": self.findings,
            "claims_file": str(self.claims_path),
            "predictions": str(self.predictions),
            "predictions_sha256": self.predictions_sha256,
            "engine": {
                "ran": self.engine_ran,
                "command": self.engine_command,
                "exit_code": self.engine_exit_code,
            },
            "offline": {
                "socket_events_observed": len(self.socket_events),
                "events": list(self.socket_events),
                "model_endpoint_configured": self.model_endpoint_configured,
            },
            "paths": [summary.payload() for summary in self.paths],
            "invariance": {
                "rows_compared": self.findings,
                "claims_with_at_least_one_status_change": self.claims_with_a_change,
                "statuses_changed_between_paths": len(self.between_paths),
                "statuses_changed_vs_engine": {
                    label: len(changes) for label, changes in self.vs_engine.items()
                },
                "immutable_field_changes": {
                    label: len(changes) for label, changes in self.field_changes.items()
                },
                "statuses_changed_by_rule": self.changes_by_rule,
                "statuses_changed_by_engine_status": self.changes_by_engine_status,
                "between_paths": [change.payload() for change in self.between_paths],
            },
            "invariant_ok": self.invariant_ok,
        }


def run_ablation(
    *,
    inputs: Inputs,
    split: str,
    workdir: Path,
    pred: Path | None,
    python: str,
    timeout: float,
) -> AblationRun:
    """Run the engine (unless reused), both provider paths, and the invariance comparison."""
    if not inputs.claims.is_file():
        raise AblationError(f"claim file not found: {inputs.claims}")
    if not inputs.rules_dir.is_dir():
        raise AblationError(f"rule catalogue directory not found: {inputs.rules_dir}")
    try:
        rules = RuleContext.from_rules_dir(inputs.rules_dir)
    except (RuleDirError, OSError, ValueError) as exc:
        raise AblationError(f"cannot load the rule catalogue: {exc}") from exc

    predictions = pred if pred is not None else workdir / split / "engine_results.jsonl"
    engine: EngineRun | None = None
    if pred is None:
        try:
            engine = run_engine(
                python=python,
                claims=inputs.claims,
                rules_dir=inputs.rules_dir,
                output=predictions,
                timeout=timeout,
            )
        except ReportError as exc:
            raise AblationError(f"the engine could not run: {exc}") from exc
        if engine.exit_code != 0:
            raise AblationError(
                f"the engine exited {engine.exit_code}: {engine.stderr.strip()[:400]}"
            )
    elif not predictions.is_file():
        raise AblationError(f"result file not found: {predictions}")

    claims = load_jsonl(inputs.claims)
    records = load_jsonl(predictions)
    grouped = group_by_claim(records)
    known = {str(claim.get("claim_id")) for claim in claims}
    if set(grouped) != known:
        missing = sorted(known - set(grouped))[:5]
        extra = sorted(set(grouped) - known)[:5]
        raise AblationError(
            f"results do not pair with the claims: no results for {missing}, "
            f"results for unknown claims {extra}"
        )

    paths = provider_paths()
    engine_records: list[Mapping[str, Any]] = []
    enriched: dict[str, list[dict[str, Any]]] = {path.label: [] for path in paths}
    outcomes: dict[str, list[ExplanationOutcome]] = {path.label: [] for path in paths}

    guard = NetworkGuard()
    with guard:
        for claim in claims:
            claim_id = str(claim.get("claim_id"))
            rows = grouped[claim_id]
            engine_records.extend(rows)
            for path in paths:
                # The ORIGINAL envelope is supplied, so citation resolution and the claim-id
                # check are active; untrusted claim text is withheld (the layer's default).
                served = explain_records(rows, rules, path.provider, envelope=claim)
                outcomes[path.label].extend(served)
                enriched[path.label].extend(apply_outcomes(rows, served))

    if any(len(items) != len(engine_records) for items in outcomes.values()):
        raise AblationError("a provider path did not serve every finding of the split")

    engine_index = index_records(engine_records)
    path_index = {label: index_records(rows) for label, rows in enriched.items()}
    labels = [path.label for path in paths]
    left, right = labels
    between_paths = status_changes(path_index[left], path_index[right])
    vs_engine = {label: tuple(status_changes(engine_index, path_index[label])) for label in labels}
    field_changes = {
        label: tuple(immutable_changes(engine_records, enriched[label])) for label in labels
    }

    return AblationRun(
        split=split,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        claims=len(claims),
        findings=len(engine_records),
        claims_path=inputs.claims,
        predictions=predictions,
        predictions_sha256=sha256_file(predictions),
        engine_command=(
            " ".join(engine.command) if engine is not None else f"(reused {predictions})"
        ),
        engine_exit_code=engine.exit_code if engine is not None else 0,
        engine_ran=engine is not None,
        model_endpoint_configured=ModelSettings.from_env() is not None,
        socket_events=tuple(guard.events),
        paths=tuple(summarise_path(path, outcomes[path.label]) for path in paths),
        between_paths=tuple(between_paths),
        vs_engine=vs_engine,
        field_changes=field_changes,
        changes_by_rule=count_changes(between_paths, lambda change: change.rule_id),
        changes_by_engine_status=count_changes(
            between_paths,
            lambda change: str(engine_index[(change.claim_id, change.rule_id)].get(STATUS_FIELD)),
        ),
        claims_with_a_change=len({change.claim_id for change in between_paths}),
    )


def sha256_file(path: Path) -> str:
    """SHA-256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------


def _emit(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def _table(columns: Sequence[str]) -> list[str]:
    return ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def render_path_table(run: AblationRun) -> list[str]:
    """Section 1: what each path did with the whole split."""
    lines = ["### What each path did with all findings", ""]
    lines += _table(
        [
            "path",
            "provider",
            "provenance",
            "served",
            "accepted",
            "fell back",
            "declined",
            "rewritten",
        ]
    )
    for summary in run.paths:
        counts = summary.counts
        lines.append(
            _row(
                [
                    summary.label,
                    f"`{summary.provider}`",
                    summary.source_kind,
                    str(counts.served),
                    str(counts.accepted),
                    str(counts.fell_back),
                    str(counts.declined),
                    str(counts.rewritten),
                ]
            )
        )
    return lines


def render_reason_table(run: AblationRun, max_texts: int) -> list[str]:
    """Section 2: why explanations were rejected, fell back or were declined."""
    lines = ["### Reasons attached to outcomes", ""]
    lines += _table(["path", "reason category", "count"])
    for summary in run.paths:
        if not summary.reasons:
            lines.append(_row([summary.label, "(none)", "0"]))
            continue
        for category, count in summary.reasons.items():
            lines.append(_row([summary.label, category, str(count)]))
    lines += ["", f"Exact reason texts (first {max_texts} per path, by frequency):", ""]
    for summary in run.paths:
        lines.append(f"- **{summary.label}**")
        if not summary.reason_texts:
            lines.append("  - (no reason was recorded: every finding was accepted as written)")
            continue
        for text, count in list(summary.reason_texts.items())[:max_texts]:
            lines.append(f"  - {count} times: {text}")
    return lines


def render_cross_table(
    heading: str,
    key_name: str,
    names: Sequence[str],
    summaries: Sequence[PathSummary],
    group_of: Callable[[PathSummary], Mapping[str, Counts]],
    changed: Mapping[str, int],
) -> list[str]:
    """One row per group name, one triple of columns per provider path."""
    columns = [key_name, "served"]
    for summary in summaries:
        columns += [
            f"{summary.label}: accepted",
            f"{summary.label}: fell back",
            f"{summary.label}: declined",
        ]
    columns.append("statuses moved")
    lines = [f"### {heading}", ""]
    lines += _table(columns)
    for name in names:
        groups = [group_of(summary).get(name, Counts()) for summary in summaries]
        cells = [name, str(sum(group.served for group in groups))]
        for group in groups:
            cells += [str(group.accepted), str(group.fell_back), str(group.declined)]
        cells.append(str(changed.get(name, 0)))
        lines.append(_row(cells))
    return lines


def render_invariance_table(run: AblationRun) -> list[str]:
    """Section 5: the status-change counts, which must be zero."""
    columns = ["comparison", "rows compared", "statuses changed"]
    lines = ["### Status invariance", ""]
    lines += _table(columns)
    left, right = (summary.label for summary in run.paths)
    lines.append(_row([f"{left} vs {right}", str(run.findings), str(len(run.between_paths))]))
    for label, changes in run.vs_engine.items():
        lines.append(_row([f"{label} vs engine output", str(run.findings), str(len(changes))]))
    for label, changes in run.field_changes.items():
        lines.append(
            _row(
                [
                    f"{label}: fields other than `{MUTABLE_FIELD}` changed",
                    str(run.findings),
                    str(len(changes)),
                ]
            )
        )
    lines += [
        "",
        f"claims with at least one moved status: {run.claims_with_a_change} of {run.claims}",
    ]
    if run.between_paths:
        lines.append("")
        lines.append("moved statuses (first 10):")
        for change in run.between_paths[:10]:
            lines.append(f"- {change.claim_id} / {change.rule_id}: {change.left} -> {change.right}")
    return lines


def render_report(run: AblationRun, max_texts: int = MAX_REASONS_PRINTED) -> str:
    """Render the whole ablation transcript."""
    lines = [
        f"ClaimGuard AI assistance ablation — split={run.split}",
        "synthetic teaching data; the system reviews, it never approves, denies or pays a claim",
        "",
        f"claims file  : {run.claims_path}",
        f"claims       : {run.claims}",
        f"findings     : {run.findings} (15 per claim)",
        f"engine       : {run.engine_command} (exit {run.engine_exit_code})",
        f"results      : {run.predictions} (sha256 {run.predictions_sha256[:16]}…)",
        f"offline      : {len(run.socket_events)} socket event(s) observed while armed; "
        f"model endpoint configured: {'yes' if run.model_endpoint_configured else 'no'}",
        "",
        "Paths:",
    ]
    for summary in run.paths:
        lines.append(f"- `{summary.label}` — {summary.expectation}")
    lines.append("")
    lines += render_path_table(run)
    lines += [""]
    lines += render_reason_table(run, max_texts)
    lines += [""]
    lines += render_cross_table(
        "By rule",
        "rule",
        list(RULE_IDS),
        run.paths,
        lambda summary: summary.by_rule,
        run.changes_by_rule,
    )
    lines += [""]
    lines += render_cross_table(
        "By status",
        "status",
        ordered_names(STATUS_ORDER, [name for s in run.paths for name in s.by_status]),
        run.paths,
        lambda summary: summary.by_status,
        run.changes_by_engine_status,
    )
    lines += [""]
    lines += render_invariance_table(run)
    lines += [""]
    lines.append(
        "RESULT: PASS — the assistance layer moved no status on either path"
        if run.invariant_ok
        else "RESULT: FAIL — the assistance layer moved at least one status; see the tables above"
    )
    return "\n".join(lines)


def ordered_names(order: Sequence[str], observed: Iterable[str]) -> list[str]:
    """``order`` first, then any unexpected names in sorted order (so none is hidden)."""
    names = [name for name in order if name in set(observed)]
    return names + sorted(set(observed) - set(order))


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python scripts/ai_ablation.py",
        description=(
            "Ablate the AI assistance layer over one split: the deterministic template provider "
            "against a provider that fails like an unavailable model, with the status-change count."
        ),
    )
    parser.add_argument("--split", choices=list(SPLITS), default="development")
    parser.add_argument(
        "--pack-root", default=None, help="mentor pack root (default: auto-discover)"
    )
    parser.add_argument(
        "--claims", default=None, help="claim envelope JSONL (default: <pack>/data/<split>/)"
    )
    parser.add_argument(
        "--rules-dir", default=None, help="rule catalogue directory (default: <pack>/rules)"
    )
    parser.add_argument(
        "--pred", default=None, help="reuse an existing engine result file instead of running it"
    )
    parser.add_argument("--workdir", default=DEFAULT_WORKDIR, help="where results are written")
    parser.add_argument("--python", default=sys.executable, help="interpreter for subprocesses")
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds for the engine run"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ablation and return a process exit code."""
    args = parse_args(argv)
    workdir = Path(args.workdir)
    try:
        inputs = resolve_inputs(args.claims, args.rules_dir, args.pack_root, args.split)
        run = run_ablation(
            inputs=inputs,
            split=args.split,
            workdir=workdir,
            pred=Path(args.pred) if args.pred else None,
            python=args.python,
            timeout=args.timeout,
        )
    except (AblationError, NetworkAttemptedError, ConformanceError) as exc:
        _emit(f"REFUSED: {exc}")
        return EXIT_REFUSED

    summary_path = workdir / args.split / "ai_ablation.json"
    write_json(summary_path, run.payload())
    _emit(render_report(run))
    _emit("")
    _emit(f"machine-readable summary: {summary_path}")
    return EXIT_OK if run.invariant_ok else EXIT_INVARIANCE_VIOLATED


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
