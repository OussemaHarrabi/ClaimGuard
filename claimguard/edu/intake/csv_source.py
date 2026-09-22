"""Relational CSV export of a split -> the pack's normalized envelope JSONL (INT-01).

docs/03_Data_Dictionary.md, "CSV relationships"::

    Each split has csv/claims.csv (one row per claim), coverage.csv (one row per
    claim), lines.csv, authorizations.csv and attachments.csv. Join all child
    files by claim_id. Empty CSV cells map to JSON null; no empty-string business
    values are generated. The converter knows the numeric columns and preserves
    record and line order. Round-trip checks are included in validate_pack.py.

This module is that converter, with the shape of the join taken from the frozen
transport contract (:data:`claimguard.edu.envelope.ENVELOPE_KEYS` and its nested
key tuples) instead of being restated here: a CSV export that drifts from the
contract is rejected, not coerced.

The rebuild is *total and ordered*: every ``claims.csv`` row becomes exactly one
17-key envelope, children are appended in file order, and a structural surprise —
missing file, missing/unknown column, ragged row, unknown ``claim_id``, duplicate
``claim_id``, duplicate or absent coverage row — raises :class:`CsvIntakeError` so
a caller cannot mistake a partial rebuild for a complete one
(docs/03_Data_Dictionary.md, "Nulls, keys and transport errors": quarantine and
report, never silently drop).

Money and quantities are :class:`~decimal.Decimal`, derived from the cell literal
("Prices use decimal arithmetic; do not round with binary floating-point
comparisons"), and are written back with :func:`claimguard.edu.intake.dump_envelope`
as the exact literal the cell spelled. The rebuilt JSONL is therefore
byte-identical to the pack's own authoritative ``claims.jsonl``.

CLI::

    python -m claimguard.edu.intake.csv_source --folder <split>/csv --output <out.jsonl>
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

from claimguard.edu.envelope import (
    ATTACHMENT_KEYS,
    AUTHORIZATION_KEYS,
    COVERAGE_KEYS,
    ENVELOPE_KEYS,
    LINE_KEYS,
)
from claimguard.edu.intake import ARRAY_CONTAINER_KEYS, CHILD_KEYS, Envelope, dump_envelope

PROGRAM: Final = "python -m claimguard.edu.intake.csv_source"
EXIT_OK: Final = 0
EXIT_INPUT_ERROR: Final = 2

CLAIMS_FILE: Final = "claims.csv"

#: Envelope key -> the child file that supplies it (docs/03, "CSV relationships").
CHILD_FILES: Final[Mapping[str, str]] = {
    "coverage": "coverage.csv",
    "lines": "lines.csv",
    "authorizations": "authorizations.csv",
    "attachments": "attachments.csv",
}

#: ``claims.csv`` columns: the scalar envelope keys, in contract order.
CLAIM_COLUMNS: Final = tuple(key for key in ENVELOPE_KEYS if key not in CHILD_FILES)

#: Required columns per file — the transport contract, plus the join key.
COLUMNS: Final[Mapping[str, tuple[str, ...]]] = {
    CLAIMS_FILE: CLAIM_COLUMNS,
    "coverage.csv": ("claim_id", *COVERAGE_KEYS),
    "lines.csv": ("claim_id", *LINE_KEYS),
    "authorizations.csv": ("claim_id", *AUTHORIZATION_KEYS),
    "attachments.csv": ("claim_id", *ATTACHMENT_KEYS),
}

#: Columns the converter reads as numbers (docs/03: "The converter knows the
#: numeric columns"). Everything else is a string or null.
NUMERIC_COLUMNS: Final[Mapping[str, frozenset[str]]] = {
    CLAIMS_FILE: frozenset({"total_amount"}),
    "coverage.csv": frozenset(),
    "lines.csv": frozenset({"quantity", "unit_price", "net_amount"}),
    "authorizations.csv": frozenset({"max_quantity"}),
    "attachments.csv": frozenset(),
}

#: Plain decimal notation only — what the pack emits for every numeric cell. An
#: exponent spelling is rejected rather than re-spelled: ``Decimal("1e3")`` renders
#: as ``1E+3``, which is not a JSON number, so accepting it would break the
#: byte-identical round trip this converter guarantees.
PLAIN_NUMBER: Final = re.compile(r"-?\d+(?:\.\d+)?")


class CsvIntakeError(ValueError):
    """The CSV export does not line up with the envelope transport contract."""


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------


def _text(cell: str | None) -> str | None:
    """One cell as an envelope value: an empty cell is JSON null (docs/03).

    "Empty CSV cells map to JSON null; no empty-string business values are
    generated" — so the empty cell and the absent cell both mean *missing*, and
    a present cell is taken verbatim (never trimmed or repaired).
    """
    return cell if cell else None


def _number(cell: str | None) -> Decimal | None:
    """One numeric cell as an exact :class:`~decimal.Decimal`, or null."""
    text = _text(cell)
    if text is None:
        return None
    if not PLAIN_NUMBER.fullmatch(text):
        raise CsvIntakeError(f"not a plain decimal number: {text!r}")
    try:
        return Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - the grammar above is decimal
        raise CsvIntakeError(f"not a decimal number: {text!r}") from exc


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _read_rows(path: Path, columns: tuple[str, ...]) -> list[dict[str, str | None]]:
    """Read one CSV file, rejecting any header that is not exactly ``columns``."""
    if not path.is_file():
        raise CsvIntakeError(f"missing CSV file: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames
        if header is None:
            raise CsvIntakeError(f"{path.name}: empty file (no header row)")
        missing = [column for column in columns if column not in header]
        unknown = [column for column in header if column not in columns]
        if missing or unknown:
            raise CsvIntakeError(
                f"{path.name}: columns do not match the transport contract"
                f" (missing={missing}, unknown={unknown})"
            )
        rows: list[dict[str, str | None]] = []
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise CsvIntakeError(f"{path.name}:{line_number}: ragged row (extra cells)")
            rows.append(dict(row))
        return rows


def _record(row: Mapping[str, str | None], child: str) -> dict[str, Any]:
    """Project one CSV row of ``child`` onto its envelope contract keys."""
    numeric = NUMERIC_COLUMNS[CHILD_FILES[child]]
    return {
        key: (_number(row[key]) if key in numeric else _text(row[key])) for key in CHILD_KEYS[child]
    }


def _group_by_claim(
    rows: Sequence[Mapping[str, str | None]], filename: str, claim_ids: set[str]
) -> dict[str, list[Mapping[str, str | None]]]:
    """Group child rows by ``claim_id``, preserving file order within each claim."""
    grouped: dict[str, list[Mapping[str, str | None]]] = {}
    for row in rows:
        claim_id = _text(row["claim_id"])
        if claim_id is None:
            raise CsvIntakeError(f"{filename}: a child row has no claim_id")
        if claim_id not in claim_ids:
            raise CsvIntakeError(f"{filename}: references unknown claim_id {claim_id!r}")
        grouped.setdefault(claim_id, []).append(row)
    return grouped


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------


def read_csv_split(folder: str | Path) -> list[Envelope]:
    """Rebuild one split's normalized envelopes from its ``csv/`` folder.

    Envelopes come back in ``claims.csv`` order, each with the 17 contract keys in
    contract order and its children in their own file order. Numeric fields are
    :class:`~decimal.Decimal`; serialize with
    :func:`claimguard.edu.intake.dump_envelope`.
    """
    directory = Path(folder)
    claim_rows = _read_rows(directory / CLAIMS_FILE, COLUMNS[CLAIMS_FILE])

    identified: list[tuple[str, Mapping[str, str | None]]] = []
    claim_ids: set[str] = set()
    for row in claim_rows:
        claim_id = _text(row["claim_id"])
        if claim_id is None:
            raise CsvIntakeError(f"{CLAIMS_FILE}: a row has no claim_id")
        if claim_id in claim_ids:
            raise CsvIntakeError(f"{CLAIMS_FILE}: duplicate claim_id {claim_id!r}")
        claim_ids.add(claim_id)
        identified.append((claim_id, row))

    children = {
        child: _group_by_claim(
            _read_rows(directory / filename, COLUMNS[filename]), filename, claim_ids
        )
        for child, filename in CHILD_FILES.items()
    }

    envelopes: list[Envelope] = []
    for claim_id, row in identified:
        coverage_rows = children["coverage"].get(claim_id, [])
        if len(coverage_rows) != 1:
            raise CsvIntakeError(
                f"{CHILD_FILES['coverage']}: {len(coverage_rows)} row(s) for claim_id"
                f" {claim_id!r}; the envelope requires exactly one coverage record"
            )
        numeric = NUMERIC_COLUMNS[CLAIMS_FILE]
        envelope: dict[str, Any] = {
            key: (_number(row[key]) if key in numeric else _text(row[key])) for key in CLAIM_COLUMNS
        }
        envelope["coverage"] = _record(coverage_rows[0], "coverage")
        for child in ARRAY_CONTAINER_KEYS:
            envelope[child] = [_record(entry, child) for entry in children[child].get(claim_id, [])]
        envelopes.append({key: envelope[key] for key in ENVELOPE_KEYS})
    return envelopes


def rebuild_jsonl(folder: str | Path, output: str | Path) -> int:
    """Rebuild one split and write it as canonical JSONL; returns the claim count.

    The output file is UTF-8 with LF line endings on every platform — the pack's
    own export format — so the rebuilt file is byte-identical to the authoritative
    ``claims.jsonl`` rather than differing by Windows line translation.
    """
    envelopes = read_csv_split(folder)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for envelope in envelopes:
            handle.write(f"{dump_envelope(envelope)}\n")
    return len(envelopes)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Rebuild the pack's normalized claim envelopes from its relational CSV export.",
    )
    parser.add_argument("--folder", required=True, help="split csv/ directory to read")
    parser.add_argument("--output", required=True, help="destination JSONL for the envelopes")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Rebuild from ``--folder`` into ``--output``; returns a process exit code."""
    args = build_parser().parse_args(argv)
    try:
        count = rebuild_jsonl(args.folder, args.output)
    except (CsvIntakeError, OSError) as exc:
        sys.stderr.write(f"claimguard.edu.intake: cannot rebuild: {exc}\n")
        return EXIT_INPUT_ERROR
    sys.stderr.write(
        f"claimguard.edu.intake: claims={count} source={args.folder} output={args.output}\n"
    )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
