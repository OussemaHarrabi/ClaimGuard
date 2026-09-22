"""CSV intake: the relational export must rebuild the authoritative envelopes.

docs/03_Data_Dictionary.md, "CSV relationships", promises that the converter
"knows the numeric columns and preserves record and line order", that "empty CSV
cells map to JSON null" and that round-trip checks exist. These tests hold this
rebuild to the strongest available form of that promise: byte equality with the
pack's own ``claims.jsonl`` for all three public splits, plus the join and
number/null boundaries the byte check would not localise, plus the end-to-end
proof that the rebuilt file drives the frozen engine to the same statuses.
"""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from claimguard.edu.envelope import ENVELOPE_KEYS
from claimguard.edu.intake import dump_envelope
from claimguard.edu.intake.csv_source import (
    CsvIntakeError,
    main,
    read_csv_split,
    rebuild_jsonl,
)

from tests.edu import PACK_ROOT, RULES_DIR, requires_pack

SPLITS = ("development", "validation", "stress")

CLAIM_HEADER = (
    "schema_version,claim_id,invoice_number,patient_id,member_id,provider_id,payer_id,"
    "policy_id,diagnosis_code,submission_date,currency,total_amount,notes"
)


# ---------------------------------------------------------------------------
# Byte equality with the authoritative export
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("split", SPLITS)
@requires_pack
def test_rebuild_is_byte_identical_to_the_pack_export(split: str, tmp_path: Path) -> None:
    """Every public split: the CSV rebuild equals ``claims.jsonl`` byte for byte."""
    authoritative = (PACK_ROOT / "data" / split / "claims.jsonl").read_bytes()
    output = tmp_path / f"{split}.jsonl"

    count = rebuild_jsonl(PACK_ROOT / "data" / split / "csv", output)

    assert count == len(authoritative.splitlines())
    assert output.read_bytes() == authoritative


@requires_pack
def test_module_cli_rebuilds_the_split(tmp_path: Path) -> None:
    """``python -m claimguard.edu.intake.csv_source`` is the documented entry point."""
    source = PACK_ROOT / "data" / "stress" / "csv"
    output = tmp_path / "nested" / "stress.jsonl"

    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        [
            sys.executable,
            "-m",
            "claimguard.edu.intake.csv_source",
            "--folder",
            str(source),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "claims=50" in completed.stderr
    assert output.read_bytes() == (PACK_ROOT / "data" / "stress" / "claims.jsonl").read_bytes()


@requires_pack
def test_rebuilt_split_drives_the_engine_to_the_same_statuses(tmp_path: Path) -> None:
    """The acceptance path: rebuild development, then run the frozen engine on both.

    The rebuilt file must reproduce every ``(claim_id, rule_id, status)`` of a run
    over the authoritative ``claims.jsonl`` — diff count zero — with all 15 rules per
    claim present.
    """
    folder = PACK_ROOT / "data" / "development"
    rebuilt = tmp_path / "rebuilt.jsonl"
    assert rebuild_jsonl(folder / "csv", rebuilt) == 400

    results = tmp_path / "results"
    for claims, stem in ((folder / "claims.jsonl", "direct"), (rebuilt, "rebuilt")):
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
            [
                sys.executable,
                "-m",
                "claimguard.edu.run",
                "--claims",
                str(claims),
                "--rules-dir",
                str(RULES_DIR),
                "--output",
                str(results / f"{stem}.jsonl"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

    direct = _statuses(results / "direct.jsonl")
    assert direct == _statuses(results / "rebuilt.jsonl")
    assert len(direct) == 400 * 15
    assert len({claim_id for claim_id, _, _ in direct}) == 400


def _statuses(path: Path) -> list[tuple[str, str, str]]:
    """The ``(claim_id, rule_id, status)`` triples of an engine result file."""
    triples: list[tuple[str, str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = cast("dict[str, Any]", json.loads(line))
        triples.append((str(record["claim_id"]), str(record["rule_id"]), str(record["status"])))
    return triples


# ---------------------------------------------------------------------------
# Join, order, null and number semantics on a hand-built export
# ---------------------------------------------------------------------------


def _write(path: Path, header: str, rows: list[str]) -> None:
    """Write one CRLF CSV file the way a spreadsheet export would."""
    path.write_bytes(("\r\n".join([header, *rows]) + "\r\n").encode("utf-8"))


@pytest.fixture
def tiny_export(tmp_path: Path) -> Path:
    """A three-claim export exercising the empty cell, ordering and number rules."""
    folder = tmp_path / "csv"
    folder.mkdir()
    _write(
        folder / "claims.csv",
        CLAIM_HEADER,
        [
            "1.0.0,CG-1,INV-1,PAT-1,,EDU-PROV-01,EDU-PAYER,EDU-BASIC,DX-1,2026-01-05,SAR,250.01,"
            '"Synthetic, quoted ""note""."',
            "1.0.0,CG-2,,PAT-2,MEM-2,EDU-PROV-01,EDU-PAYER,EDU-BASIC,,2026-01-06,SAR,270.0,x",
        ],
    )
    _write(
        folder / "coverage.csv",
        "claim_id,coverage_id,status,beneficiary_patient_id,member_id,start_date,end_date",
        [
            "CG-1,COV-1,active,PAT-1,,2026-01-01,",
            "CG-2,COV-2,active,PAT-2,MEM-2,2026-01-01,2026-12-31",
        ],
    )
    # Line rows deliberately out of line_id order: order must follow the file.
    _write(
        folder / "lines.csv",
        "claim_id,line_id,service_code,service_date,modifier,quantity,unit_price,net_amount,"
        "authorization_id",
        [
            "CG-1,L2,SVC-IMAGE,2026-01-05,,1,110.5,110.5,AUTH-1",
            "CG-1,L1,SVC-LAB,2026-01-05,,2.5,,25,",
            "CG-2,L1,SVC-CONSULT,2026-01-06,25,1,270.0,270.0,",
        ],
    )
    _write(
        folder / "authorizations.csv",
        "claim_id,authorization_id,patient_id,service_code,status,valid_from,valid_to,max_quantity",
        ["CG-1,AUTH-1,PAT-1,SVC-IMAGE,approved,2026-01-01,2026-02-01,10"],
    )
    _write(
        folder / "attachments.csv",
        "claim_id,attachment_id,type,patient_id,service_code,service_date,document_status,text",
        ["CG-1,DOC-1,imaging-report,PAT-9,SVC-IMAGE,2026-01-05,final,SYNTHETIC TRAINING DOCUMENT."],
    )
    return folder


def test_join_order_nulls_and_numbers(tiny_export: Path) -> None:
    """Children join by claim_id, keep file order, and empty cells become null."""
    first, second = read_csv_split(tiny_export)

    assert list(first) == list(ENVELOPE_KEYS)
    assert list(second) == list(ENVELOPE_KEYS)
    assert first["invoice_number"] == "INV-1"
    assert second["invoice_number"] is None
    assert first["member_id"] is None
    assert first["notes"] == 'Synthetic, quoted "note".'
    assert first["coverage"]["end_date"] is None
    assert first["coverage"]["member_id"] is None
    assert [line["line_id"] for line in first["lines"]] == ["L2", "L1"]
    assert [line["unit_price"] for line in first["lines"]] == [Decimal("110.5"), None]
    assert [line["quantity"] for line in first["lines"]] == [Decimal("1"), Decimal("2.5")]
    assert second["diagnosis_code"] is None
    assert second["authorizations"] == []
    assert second["attachments"] == []
    assert second["lines"][0]["modifier"] == "25"


def test_money_is_exact_decimal_not_binary_float(tiny_export: Path) -> None:
    """Money and quantities are Decimal, and the rendered text keeps the literal."""
    first, second = read_csv_split(tiny_export)

    assert first["total_amount"] == Decimal("250.01")
    assert second["total_amount"] == Decimal("270.0")
    assert isinstance(first["lines"][0]["net_amount"], Decimal)
    assert [line["unit_price"] for line in first["lines"]] == [Decimal("110.5"), None]

    rendered = dump_envelope(first)
    parsed = cast("dict[str, Any]", json.loads(rendered))
    assert parsed["total_amount"] == 250.01
    assert parsed["invoice_number"] == "INV-1"
    assert parsed["member_id"] is None
    assert parsed["coverage"]["end_date"] is None
    assert '"total_amount": 250.01' in rendered
    assert '"quantity": 1' in rendered


def test_cli_writes_what_the_library_returns(tiny_export: Path, tmp_path: Path) -> None:
    """The CLI entry point writes the same canonical JSONL as the library."""
    output = tmp_path / "out.jsonl"

    assert main(["--folder", str(tiny_export), "--output", str(output)]) == 0

    expected = "".join(f"{dump_envelope(claim)}\n" for claim in read_csv_split(tiny_export))
    assert output.read_text(encoding="utf-8") == expected
    assert "\r\n" not in output.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The rebuild is total: structural surprises are errors, never silent loss
# ---------------------------------------------------------------------------


def test_unknown_column_is_rejected(tiny_export: Path) -> None:
    """An export that gained a column would silently lose data, so it is refused."""
    (tiny_export / "lines.csv").write_bytes(
        (tiny_export / "lines.csv").read_bytes().replace(b"authorization_id", b"auth_ref")
    )

    with pytest.raises(CsvIntakeError, match="authorization_id"):
        read_csv_split(tiny_export)


def test_orphan_child_row_is_rejected(tiny_export: Path) -> None:
    """A child row for a claim that is not in claims.csv is a broken join."""
    with (tiny_export / "authorizations.csv").open("a", encoding="utf-8", newline="") as handle:
        handle.write("CG-404,AUTH-X,PAT-X,SVC-LAB,approved,2026-01-01,2026-02-01,1\n")

    with pytest.raises(CsvIntakeError, match="CG-404"):
        read_csv_split(tiny_export)


def test_duplicate_claim_row_is_rejected(tiny_export: Path) -> None:
    """Two rows for one claim_id cannot both become the claim's envelope."""
    with (tiny_export / "claims.csv").open("a", encoding="utf-8", newline="") as handle:
        handle.write(
            "1.0.0,CG-1,INV-1,PAT-1,,EDU-PROV-01,EDU-PAYER,EDU-BASIC,DX-1,2026-01-05,SAR,1,x\n"
        )

    with pytest.raises(CsvIntakeError, match="duplicate claim_id"):
        read_csv_split(tiny_export)


def test_missing_coverage_row_is_rejected(tiny_export: Path) -> None:
    """The envelope requires exactly one coverage record per claim."""
    body = (tiny_export / "coverage.csv").read_bytes()
    (tiny_export / "coverage.csv").write_bytes(
        body.replace(b"CG-2,COV-2,active,PAT-2,MEM-2,2026-01-01,2026-12-31\r\n", b"")
    )

    with pytest.raises(CsvIntakeError, match="coverage"):
        read_csv_split(tiny_export)
