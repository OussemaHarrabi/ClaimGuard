"""The ``claimguard`` console: the argument surface, and the dispatch table.

Four commands, no hidden ones. ``claimguard --help`` lists them; each has its own ``--help``
with the prerequisites it checks. Every command returns a process exit code, so the console
can be used as a gate rather than only as a convenience.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import cast

from claimguard.cli import evaluate, report, serve, status
from claimguard.cli.evaluate import DEFAULT_WORKDIR as EVALUATE_WORKDIR
from claimguard.cli.serve import DEFAULT_HOST, DEFAULT_PORT
from claimguard.cli.tooling import SPLITS

#: ``command -> the function that runs it``. Adding a command means adding it here too, which
#: is what keeps the parser and the behaviour from drifting apart.
COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "status": status.run,
    "serve": serve.run,
    "evaluate": evaluate.run,
    "report": report.run,
}

EPILOG = """\
exit codes
  status    0 ready, 1 degraded (a check failed; the reason is printed)
  evaluate  0 conformant, 1 non-conformant, 2 refused (missing pack, or the engine failed)
  report    0 written and conformant, 1 written but non-conformant, 2 refused
  serve     uvicorn's own

examples
  claimguard status
  claimguard serve --reload
  claimguard evaluate --split all
  claimguard report --split development --output docs/verification/EDU-EVALUATION-REPORT.md
"""


def build_parser() -> argparse.ArgumentParser:
    """Build the full argument surface (``--help`` is the documentation of record)."""
    parser = argparse.ArgumentParser(
        prog="claimguard",
        description=(
            "ClaimGuard AI operator console. Every command runs the repository's existing "
            "engine, scorer or report generator; none of them re-implements a rule and none "
            "of them decides anything about a claim."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    subparsers.add_parser(
        "status",
        help="readiness: the contract in force, the rule catalogue, the database revision",
        description=(
            "Report what this checkout would actually run: the decision record that fixes the "
            "graded contract, the rule catalogue the engine and the API would load, and "
            "whether the review schema is reachable and migrated."
        ),
    )

    serve_parser = subparsers.add_parser(
        "serve",
        help="start the reviewer API (uvicorn, factory claimguard.review.app:create_app)",
        description=(
            "Start the reviewer API and UI. Run from the repository root: --reload watches "
            "the current directory. The rule catalogue resolves from CLAIMGUARD_RULES_DIR or "
            "CLAIMGUARD_PACK_ROOT; the DSN from CLAIMGUARD_DATABASE_URL."
        ),
    )
    serve_parser.add_argument("--host", default=DEFAULT_HOST, help="interface to bind")
    serve_parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port to bind")
    serve_parser.add_argument(
        "--reload",
        action="store_true",
        help="restart on source changes (development only)",
    )

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="run the engine over a pack split, then score it with the mentor's scorer",
        description=(
            "Run the deterministic engine over one split (or all three) and score the result "
            "with the mentor's strict scorer plus the independent conformance harness. Exit "
            "code 0 means the gate passed; a refused split is never scored."
        ),
    )
    evaluate_parser.add_argument(
        "--split",
        choices=[*SPLITS, "all"],
        default="all",
        help="pack split to evaluate, or every split the gate covers",
    )
    evaluate_parser.add_argument(
        "--pack-root",
        default=None,
        help="mentor pack root (default: discovered, or CLAIMGUARD_PACK_ROOT)",
    )
    evaluate_parser.add_argument(
        "--workdir",
        default=EVALUATE_WORKDIR,
        help="where predictions and the per-split harness reports are written",
    )
    evaluate_parser.add_argument(
        "--engine-only",
        action="store_true",
        help="write the predictions and stop, without scoring them",
    )

    report_parser = subparsers.add_parser(
        "report",
        help="generate the versioned evaluation report for one split",
        description=(
            "Evaluate one split and write the Markdown evaluation report. The report is "
            "refused, not written, if the mentor's scorer rejects the run."
        ),
    )
    report_parser.add_argument("--split", choices=list(SPLITS), default="development")
    report_parser.add_argument("--output", required=True, help="destination Markdown report")
    report_parser.add_argument(
        "--pack-root",
        default=None,
        help="mentor pack root (default: discovered, or CLAIMGUARD_PACK_ROOT)",
    )
    report_parser.add_argument(
        "--workdir",
        default=None,
        help="where the generator writes predictions and metrics (default: its own)",
    )
    report_parser.add_argument(
        "--baseline",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="also score the pack's own baseline for the reference comparison",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` (default: ``sys.argv``) and run the requested command."""
    args = build_parser().parse_args(argv)
    return COMMANDS[cast(str, args.command)](args)
