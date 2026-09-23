"""``claimguard report`` — the versioned evaluation report.

Runs ``scripts/edu_report.py``, which evaluates one split (engine, then the mentor's scorer,
then the independent harness) and writes the Markdown report that carries the dataset and
catalogue identity, the full metric set, the per-rule table, the confusion matrix, the error
analysis and the pack's honesty statements.

The report is refused rather than written if the mentor's scorer rejects the run, so a
non-conformant run cannot leave a plausible-looking document behind. ``--output`` is required:
overwriting the report committed under ``docs/verification/`` is a deliberate act.
"""

from __future__ import annotations

import argparse
from typing import Final, cast

from claimguard.cli.tooling import ToolingError, refuse, resolve_pack, run_script, script

#: The split the committed report was generated from.
DEFAULT_SPLIT: Final = "development"


def run(args: argparse.Namespace) -> int:
    """Generate the report; the exit code is the generator's own."""
    split = cast(str, args.split)
    output = cast(str, args.output)
    try:
        pack_root, rules_dir = resolve_pack(cast(str | None, args.pack_root))
        generator = script("edu_report.py")
    except ToolingError as exc:
        return refuse(str(exc))

    argv = [
        "--split",
        split,
        "--output",
        output,
        "--pack-root",
        str(pack_root),
        "--rules-dir",
        str(rules_dir),
    ]
    if not cast(bool, args.baseline):
        argv.append("--no-baseline")
    workdir = cast(str | None, args.workdir)
    if workdir:
        argv += ["--workdir", workdir]
    return run_script(generator, argv)
