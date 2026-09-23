"""Locating and running the repository's own frozen tooling.

The console re-implements nothing. The deterministic engine lives in
:mod:`claimguard.edu.run`, the mentor-scorer harness in ``scripts/edu_conformance.py`` and the
evaluation report generator in ``scripts/edu_report.py``. This module is the one place that
finds those entry points, resolves the mentor pack and the rule catalogue, and runs a script
with an explicit argv — never through a shell.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from claimguard.review.app import resolve_rules_dir

#: The repository root, derived from this file rather than from the working directory:
#: ``claimguard/cli/tooling.py`` -> ``claimguard/cli`` -> ``claimguard`` -> root.
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

#: Where the repository's own entry points live.
SCRIPTS_DIRNAME = "scripts"

#: The pack's directory names, relative to the pack root.
RULES_DIRNAME = "rules"
DATA_DIRNAME = "data"
CLAIMS_FILENAME = "claims.jsonl"
RULE_MANIFEST = "rules.json"

#: The splits the mentor pack ships and the harness scores. Kept in lockstep with
#: ``SPLITS`` in ``scripts/edu_conformance.py``: ``--split all`` must mean the same three
#: splits the gate runs, not whatever happens to be on disk.
SPLITS: tuple[str, ...] = ("development", "validation", "stress")


class ToolingError(RuntimeError):
    """A prerequisite of the requested command is absent (reported, never worked around)."""


#: What every command returns when a prerequisite is missing: usage/IO error, never "passed".
EXIT_REFUSED: Final = 2


def refuse(message: str) -> int:
    """Report a missing prerequisite on stderr and return the refusal exit code."""
    print(f"claimguard: {message}", file=sys.stderr)
    return EXIT_REFUSED


def script(name: str) -> Path:
    """Path to one of the repository's own ``scripts/`` entry points."""
    path = REPO_ROOT / SCRIPTS_DIRNAME / name
    if not path.is_file():
        raise ToolingError(
            f"{path} is missing: this command runs the repository's own tooling, so it needs a "
            "source checkout, not just the installed package"
        )
    return path


def resolve_pack(explicit: str | None = None) -> tuple[Path, Path]:
    """Return ``(pack_root, rules_dir)`` for the mentor pack.

    With no ``--pack-root``, the catalogue is located by
    :func:`claimguard.review.app.resolve_rules_dir` — the same resolution the API and
    ``claimguard status`` use, so every entry point agrees on which catalogue is in force.
    That resolution honours ``CLAIMGUARD_RULES_DIR`` and then ``CLAIMGUARD_PACK_ROOT``.
    """
    if explicit is not None:
        root = Path(explicit)
        rules = root / RULES_DIRNAME
    else:
        rules = resolve_rules_dir()
        root = rules.parent
    if not (rules / RULE_MANIFEST).is_file():
        raise ToolingError(
            f"no {RULE_MANIFEST} in {rules}: pass --pack-root, or set CLAIMGUARD_PACK_ROOT "
            "or CLAIMGUARD_RULES_DIR"
        )
    probe = root / DATA_DIRNAME / SPLITS[0] / CLAIMS_FILENAME
    if not probe.is_file():
        raise ToolingError(
            f"{root} holds a rule catalogue but no {probe.relative_to(root)}: pass --pack-root "
            "pointing at the mentor pack root"
        )
    return root.resolve(), rules.resolve()


def split_claims(pack_root: Path, split: str) -> Path:
    """The claim file of one pack split (a missing split is an error, never an empty run)."""
    path = pack_root / DATA_DIRNAME / split / CLAIMS_FILENAME
    if not path.is_file():
        raise ToolingError(f"{path} is missing: the pack ships no '{split}' split")
    return path


def run_script(path: Path, argv: Sequence[str]) -> int:
    """Run one of the repository's scripts and return its exit code.

    The child inherits this process's stdout and stderr, so the harness's own report — the
    evidence a judge reads — is printed verbatim rather than paraphrased here.
    """
    command = [sys.executable, str(path), *argv]
    print(f"claimguard: running {' '.join(command)}", flush=True)
    completed = subprocess.run(command, check=False)  # noqa: S603 - fixed argv, no shell
    return completed.returncode
