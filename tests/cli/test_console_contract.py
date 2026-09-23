"""The console is a gate, so its contract is the exit code — test that, not the prose.

These tests deliberately avoid asserting on wording beyond what a caller depends on
(which command ran, did it refuse, did it write a file). The expensive paths — a real
evaluation, a real report — are covered where they belong: the eval suite runs them
against the mentor's scorer, and `claimguard status` is exercised against the
catalogues this checkout actually resolves.

Only two of these tests need anything external, and neither needs the mentor pack:
the "refuses cleanly" cases point the console at a directory that does not exist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from claimguard.cli import main as cli_main
from claimguard.cli.main import COMMANDS, main

#: The catalogue our engine and API can always resolve: committed, so CI has it.
VENDORED_CATALOGUE = Path(__file__).resolve().parents[1] / "edu" / "fixtures" / "pack_reference"


def test_every_documented_command_is_dispatchable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The declared commands and the dispatch table must not drift apart.

    Compares the help text (the public surface, and what a user actually reads)
    against ``COMMANDS`` — so a command added to one and not the other fails here.
    """
    with pytest.raises(SystemExit):
        main(["--help"])
    printed = capsys.readouterr().out
    # argparse renders each subcommand as "    name  description" under
    # "positional arguments"; that block is the user-visible command list.
    documented = set(re.findall(r"(?m)^\s{4}([a-z][a-z0-9_-]*)\s{2,}\S", printed))
    assert documented == set(COMMANDS), (
        f"help lists {sorted(documented)} but the dispatch table has {sorted(COMMANDS)}"
    )


def test_help_exits_zero_and_lists_the_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    printed = capsys.readouterr().out
    for command in COMMANDS:
        assert command in printed, f"{command} is not discoverable from --help"


def test_missing_command_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2, "an absent command must be a usage error, not a silent success"


def test_evaluate_refuses_a_missing_pack_rather_than_scoring_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2, not 0: no pack means no measurement, and a gate must not pass silently."""
    code = main(
        [
            "evaluate",
            "--split",
            "development",
            "--pack-root",
            str(tmp_path / "absent"),
            "--workdir",
            str(tmp_path),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2, "a missing pack must be refused, never reported as a passed gate"
    assert "rules.json" in captured.err, "the operator must be told what was not found"
    assert "refus" not in captured.out.lower(), "a refusal is not a successful evaluation"


def test_report_refuses_and_writes_no_file_when_the_pack_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "report.md"
    code = main(
        [
            "report",
            "--split",
            "development",
            "--output",
            str(destination),
            "--pack-root",
            str(tmp_path / "absent"),
            "--no-baseline",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert not destination.exists(), "a refused run must not leave a report behind"
    assert "rules.json" in captured.err, "the operator must be told what was not found"


def test_status_reports_the_catalogue_it_would_actually_load(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pointed at the committed catalogue, status must find it and name the contract."""
    monkeypatch.setenv("CLAIMGUARD_RULES_DIR", str(VENDORED_CATALOGUE))
    code = main(["status"])
    output = capsys.readouterr().out
    assert code in (0, 1), "0 = ready, 1 = degraded; anything else is a crash"
    assert "NOT FOUND" not in output, "the committed catalogue must resolve"
    assert "R001" in output, "the catalogue line should name the rules it found"
    assert "contract" in output.lower(), "status must name the decision record in force"


def test_status_degrades_loudly_when_no_catalogue_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing catalogue is a failed check: exit 1, with the fix printed."""
    monkeypatch.setenv("CLAIMGUARD_RULES_DIR", str(tmp_path / "absent"))
    monkeypatch.setenv("CLAIMGUARD_PACK_ROOT", str(tmp_path / "absent-too"))
    code = main(["status"])
    output = capsys.readouterr().out
    assert code == 1, "an unresolved catalogue must degrade, not report ready"
    assert "NOT FOUND" in output
    assert "CLAIMGUARD_RULES_DIR" in output, "the operator must be told how to fix it"


def test_the_module_exposes_a_callable_main_for_the_console_script() -> None:
    """``pyproject.toml`` declares ``claimguard.cli.main:main``; keep that true."""
    assert callable(cli_main.main)
