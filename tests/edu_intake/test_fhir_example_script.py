"""The FHIR mapping example: the script runs end to end, and the document cannot drift from it.

Pack Required MVP behaviour 1 asks for one FHIR mapping example to be *demonstrated*. The
demonstration is three artifacts — ``scripts/fhir_example.py``, the transcript it prints, and
``docs/verification/FHIR-MAPPING-EXAMPLE.md`` — and these tests are what keeps them in step:

* the script proves what the module proves (``UNSUPPORTED_FIELDS``, ``SUPPORTED_FIELDS``,
  ``ALL_FIELD_PATHS``), and section ``[3/6]`` of its output is exactly the module's list, in the
  module's order;
* the document must contain the derived lines the script prints — every section header, every
  unsupported path and the answerability summary — so editing the module without regenerating the
  transcript fails here rather than silently re-basing the page on a stale run.

The mentor pack is delivered reference material and is absent in CI, so everything that needs a
real bundle skips cleanly (the same ``requires_pack`` guard as ``test_fhir_source.py``). The rule
table's own consistency is checked without the pack, so it is covered everywhere.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from claimguard.edu.envelope import RULE_IDS
from claimguard.edu.intake.fhir_source import (
    ALL_FIELD_PATHS,
    SUPPORTED_FIELDS,
    UNSUPPORTED_FIELDS,
)
from scripts import fhir_example

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_ROOT = REPO_ROOT / "ClaimGuardAI_Student_Starter_Pack" / "ClaimGuardAI_Student_Starter_Pack"
BUNDLES = PACK_ROOT / "data" / "development" / "fhir_bundles.jsonl"
SCRIPT = REPO_ROOT / "scripts" / "fhir_example.py"
DOCUMENT = REPO_ROOT / "docs" / "verification" / "FHIR-MAPPING-EXAMPLE.md"

requires_pack = pytest.mark.skipif(
    not BUNDLES.is_file(),
    reason="mentor starter pack absent (delivered reference material, not tracked in git)",
)

#: One unsupported path as section ``[3/6]`` prints it, with or without the marker the section
#: adds when several consecutive paths share a reason.
_UNSUPPORTED_LINE = re.compile(r"^  (/\S+)(?:  \(same reason as above\))?$")

#: The checks the bundles cannot carry enough fields for. Pinning both directions here means a
#: change to the projection's gaps, or to a rule's inputs, has to be argued rather than absorbed.
EXPECTED_NOT_ANSWERABLE = frozenset({"R009", "R010"})


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the example exactly as the document tells a reader to."""
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def section(transcript: list[str], tag: str) -> list[str]:
    """The lines of one ``[N/6]`` block, up to the next block header."""
    start = next(index for index, line in enumerate(transcript) if line.startswith(tag))
    end = next(
        (index for index in range(start + 1, len(transcript)) if transcript[index].startswith("[")),
        len(transcript),
    )
    return transcript[start:end]


@pytest.fixture(scope="module")
def transcript() -> list[str]:
    """The default run's stdout, as a reader following the document would see it."""
    completed = run_script()
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.splitlines()


# ---------------------------------------------------------------------------
# The transcription itself
# ---------------------------------------------------------------------------


def test_rule_input_table_covers_the_envelope_contract() -> None:
    """One row per rule, every declared input a real envelope path, and the documented gap."""
    assert fhir_example.unknown_input_paths() == ()
    assert tuple(rule.rule_id for rule in fhir_example.RULE_INPUTS) == RULE_IDS
    assert all(rule.inputs for rule in fhir_example.RULE_INPUTS)

    blocked = {
        rule.rule_id for rule in fhir_example.RULE_INPUTS if fhir_example.blocked_paths(rule)
    }
    assert blocked == EXPECTED_NOT_ANSWERABLE


# ---------------------------------------------------------------------------
# The script, against the pack
# ---------------------------------------------------------------------------


@requires_pack
def test_example_runs_end_to_end_over_a_real_attachment_bundle(
    transcript: list[str],
) -> None:
    """The default run reads a real bundle offline and shows the fields it recovered."""
    text = "\n".join(transcript)

    assert "network        : none used" in text
    assert "database       : none used" in text
    assert "resource(s): Claim 1" in text
    assert "DocumentReference" in text
    assert any(line.startswith("  /lines/0/service_code ") for line in transcript)
    assert any(line.startswith("  /attachments/0/attachment_id ") for line in transcript)


@requires_pack
def test_transcript_lists_exactly_the_unsupported_fields_the_module_declares(
    transcript: list[str],
) -> None:
    """Section ``[3/6]`` is the module's list, in the module's order: nothing added or dropped."""
    listed = [
        match.group(1)
        for line in section(transcript, "[3/6]")
        if (match := _UNSUPPORTED_LINE.match(line)) is not None
    ]

    assert tuple(listed) == tuple(field.path for field in UNSUPPORTED_FIELDS)


@requires_pack
def test_the_reported_counts_are_derived_from_the_module(transcript: list[str]) -> None:
    """The recovered/unsupported counts in the transcript are the module's, not prose."""
    recovered = section(transcript, "[2/6]")
    unsupported = section(transcript, "[3/6]")

    assert (
        f"can supply {len(SUPPORTED_FIELDS)} of the {len(ALL_FIELD_PATHS)} contract leaf paths"
        in recovered[1]
    )
    assert (
        f"({len(UNSUPPORTED_FIELDS)} of {len(ALL_FIELD_PATHS)} contract leaf paths)"
        in unsupported[0]
    )


@requires_pack
def test_unknown_claim_id_is_refused_rather_than_guessed() -> None:
    """``--claim-id`` with an id the split does not carry is a refusal, not an empty transcript."""
    completed = run_script("--claim-id", "CG-NOT-IN-THE-PACK")

    assert completed.returncode == 2
    assert "CG-NOT-IN-THE-PACK" in completed.stdout
    assert "[2/6]" not in completed.stdout


# ---------------------------------------------------------------------------
# The document, against the script
# ---------------------------------------------------------------------------


@requires_pack
def test_document_carries_every_line_the_module_derives(transcript: list[str]) -> None:
    """The captured page holds every section header, unsupported path and the summary.

    Lines are compared whole, not as substrings: an indented path inside another block is not
    the same line as the section ``[3/6]`` entry a reader is meant to find.
    """
    document = DOCUMENT.read_text(encoding="utf-8").splitlines()
    required = [
        line
        for line in transcript
        if line.startswith("[")
        or line.startswith("  answerable ")
        or _UNSUPPORTED_LINE.match(line) is not None
    ]

    assert len(required) == 6 + len(UNSUPPORTED_FIELDS) + 1
    missing = [line for line in required if line not in document]
    assert not missing, (
        "docs/verification/FHIR-MAPPING-EXAMPLE.md drifted from scripts/fhir_example.py:\n"
        + "\n".join(missing)
    )


@requires_pack
def test_document_transcript_is_the_script_output_verbatim(transcript: list[str]) -> None:
    """The page claims "everything verbatim", so the fenced block must be the run itself."""
    document = DOCUMENT.read_text(encoding="utf-8")
    marker = "## Captured transcript\n\n```\n"
    start = document.index(marker) + len(marker)
    block = document[start : document.index("\n```", start)]

    assert block == "\n".join(transcript)
