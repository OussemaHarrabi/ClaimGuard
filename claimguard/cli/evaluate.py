"""``claimguard evaluate`` — the engine over a pack split, scored by the mentor's own scorer.

Two existing pieces, run in the order the evidence requires:

1. :func:`claimguard.edu.run.main` — the frozen engine CLI — writes one prediction file per
   split (15 result records per claim);
2. ``scripts/edu_conformance.py`` scores those files with the mentor's strict scorer and with
   the independent re-implementation of the admissibility contract, then applies the accuracy
   gate.

The engine runs in this process and the harness runs as a child process, so its report — the
evidence a judge reads — is printed verbatim. A split the engine refuses is never scored: a
partial prediction file must not be able to look like a result.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Final, cast

from claimguard.cli.tooling import (
    SPLITS,
    ToolingError,
    refuse,
    resolve_pack,
    run_script,
    script,
    split_claims,
)
from claimguard.edu.run import main as run_engine

#: The harness's exit codes, which this command passes through unchanged.
EXIT_CONFORMANT: Final = 0
EXIT_NON_CONFORMANT: Final = 1

#: Where predictions (and the harness's per-split reports) are written by default.
DEFAULT_WORKDIR: Final = "artifacts/edu"

#: ``scripts/edu_conformance.py`` expands this placeholder once per split under ``--all``.
SPLIT_PLACEHOLDER: Final = "{split}"
PREDICTIONS_SUFFIX: Final = ".jsonl"


def run(args: argparse.Namespace) -> int:
    """Run the engine over the requested split(s), then score what it wrote."""
    requested = cast(str, args.split)
    splits: tuple[str, ...] = SPLITS if requested == "all" else (requested,)
    workdir = Path(cast(str, args.workdir))
    try:
        pack_root, rules_dir = resolve_pack(cast(str | None, args.pack_root))
        claims = {split: split_claims(pack_root, split) for split in splits}
    except ToolingError as exc:
        return refuse(str(exc))

    workdir.mkdir(parents=True, exist_ok=True)
    for split in splits:
        code = run_engine(
            [
                "--claims",
                str(claims[split]),
                "--rules-dir",
                str(rules_dir),
                "--output",
                str(workdir / f"{split}{PREDICTIONS_SUFFIX}"),
            ]
        )
        if code != EXIT_CONFORMANT:
            return refuse(
                f"the engine refused the '{split}' split (exit {code}); nothing was scored"
            )

    if cast(bool, args.engine_only):
        print(
            f"claimguard evaluate: {len(splits)} prediction file(s) under {workdir} "
            "(not scored: --engine-only)"
        )
        return EXIT_CONFORMANT

    try:
        harness = script("edu_conformance.py")
    except ToolingError as exc:
        return refuse(str(exc))
    return run_script(harness, _harness_argv(requested, workdir, pack_root))


def _harness_argv(requested: str, workdir: Path, pack_root: Path) -> Sequence[str]:
    """The harness argv for one requested split (or ``all``), paths pinned to this run."""
    argv = [
        "--pred",
        str(workdir / f"{SPLIT_PLACEHOLDER}{PREDICTIONS_SUFFIX}"),
        "--pack-root",
        str(pack_root),
        "--workdir",
        str(workdir),
    ]
    return [*argv, "--all"] if requested == "all" else [*argv, "--split", requested]
