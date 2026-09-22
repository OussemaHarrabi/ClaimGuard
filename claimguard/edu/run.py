"""Frozen CLI for the pack-conformant engine.

    python -m claimguard.edu.run --claims <claims.jsonl> \
        --rules-dir <pack/rules> --output <results.jsonl>

Emits one JSON object per line — exactly 15 records per input claim, in
R001..R015 order (docs/04_Rulebook.md:8) — and reports counts to stderr.

Input handling follows the pack's ingestion contract
(docs/03_Data_Dictionary.md, "Nulls, keys and transport errors"): a malformed
JSON line or an envelope that fails the transport contract is *quarantined* —
reported as a structured ``ingestion_error`` record (stderr plus a sidecar file
next to ``--output``) and excluded from evaluation. A defective claim is never
silently dropped, never repaired, and never emitted as a passed claim; the
process exits non-zero so a partial run cannot be mistaken for a complete one.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from claimguard.edu.emit import serialize
from claimguard.edu.engine import evaluate_claim, summarize
from claimguard.edu.envelope import (
    IngestionError,
    Result,
    load_transport_claims,
    write_jsonl,
)
from claimguard.edu.policy import RuleContext, RuleDirError

PROGRAM = "python -m claimguard.edu.run"
EXIT_OK = 0
EXIT_INPUT_ERROR = 2

#: Sidecar report of quarantined lines, written next to ``--output``.
INGESTION_REPORT_SUFFIX = ".ingestion_errors.jsonl"


def build_parser() -> argparse.ArgumentParser:
    """Build the frozen argument parser."""
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Evaluate the fictional payer rulebook over normalized claim envelopes.",
    )
    parser.add_argument("--claims", required=True, help="normalized claim envelope JSONL")
    parser.add_argument(
        "--rules-dir", required=True, help="pack rules/ directory with the JSON catalogues"
    )
    parser.add_argument("--output", required=True, help="destination JSONL for the result records")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the engine and return a process exit code (0 only for a clean input)."""
    args = build_parser().parse_args(argv)
    try:
        ctx = RuleContext.from_rules_dir(args.rules_dir)
        claims, quarantined = load_transport_claims(args.claims)
    except (RuleDirError, OSError, ValueError) as exc:
        sys.stderr.write(f"claimguard.edu: cannot start: {exc}\n")
        return EXIT_INPUT_ERROR

    if quarantined:
        _report_quarantine(quarantined, args.output)

    lines: list[str] = []
    records: list[Result] = []
    try:
        for claim in claims:
            for record in evaluate_claim(claim, ctx):
                lines.append(serialize(record, claim))
                records.append(record)
        write_jsonl(args.output, lines)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"claimguard.edu: cannot write results: {exc}\n")
        return EXIT_INPUT_ERROR

    summary = summarize(records)
    sys.stderr.write(f"claimguard.edu: claims={len(claims)} records={summary.records}\n")
    sys.stderr.write(f"claimguard.edu: by_rule={_format_counts(summary.by_rule)}\n")
    sys.stderr.write(f"claimguard.edu: by_status={_format_counts(summary.by_status)}\n")
    sys.stderr.write(f"claimguard.edu: output={args.output}\n")
    if quarantined:
        sys.stderr.write(
            f"claimguard.edu: quarantined={len(quarantined)} line(s); "
            "see the ingestion-error report; rerun after correcting the input\n"
        )
        return EXIT_INPUT_ERROR
    return EXIT_OK


def _report_quarantine(quarantined: list[IngestionError], output: str) -> None:
    """Report quarantined lines as structured records (stderr and a sidecar file)."""
    payloads = [json.dumps(error.as_dict(), sort_keys=True) for error in quarantined]
    for payload in payloads:
        sys.stderr.write(f"claimguard.edu: ingestion_error {payload}\n")
    report_path = Path(output).with_name(Path(output).name + INGESTION_REPORT_SUFFIX)
    try:
        write_jsonl(report_path, payloads)
    except OSError as exc:  # pragma: no cover - stderr already carries every record
        sys.stderr.write(f"claimguard.edu: could not write the ingestion report: {exc}\n")
        return
    sys.stderr.write(f"claimguard.edu: ingestion_report={report_path}\n")


def _format_counts(counts: Mapping[str, int]) -> str:
    """Render a ``{key: count}`` mapping as a stable ``key=count`` list."""
    return " ".join(f"{key}={counts[key]}" for key in sorted(counts))


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
