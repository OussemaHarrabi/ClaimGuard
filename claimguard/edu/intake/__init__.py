"""Intake projections from the pack's two non-authoritative sources (INT-01/02).

Normalized JSONL is the authoritative input of the benchmark
(``data/dataset_manifest.json``: ``"authoritative_format": "normalized JSONL"``).
This subpackage rebuilds or projects that envelope from the two *convenience*
formats the pack also ships, so an integration exercise never has to hand-build a
17-key record:

*   :mod:`claimguard.edu.intake.csv_source` — the relational CSV export, rebuilt
    losslessly into the same normalized envelopes (docs/03_Data_Dictionary.md,
    "CSV relationships").
*   :mod:`claimguard.edu.intake.fhir_source` — a FHIR R4 collection Bundle,
    projected onto the envelope fields the bundle actually carries; every other
    field is reported as unsupported instead of being invented
    (docs/11_FHIR_Orientation.md, "Deliberate limitations").

Shared here is the exact-number JSON writer. Money and quantities are carried as
:class:`decimal.Decimal` and never as binary float — docs/03_Data_Dictionary.md is
explicit that "Prices use decimal arithmetic; do not round with binary
floating-point comparisons" — but :func:`json.dumps` refuses ``Decimal``. Rather
than route money through ``float`` (which silently re-spells ``0.1 + 0.2``), the
record is rendered here with :func:`dump_envelope`, which is byte-identical to
``json.dumps(record, ensure_ascii=False)`` for every supported type and emits a
``Decimal`` as its exact literal (``Decimal("270.0")`` -> ``270.0``,
``Decimal("330")`` -> ``330``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final, cast

from claimguard.edu.envelope import (
    ATTACHMENT_KEYS,
    AUTHORIZATION_KEYS,
    COVERAGE_KEYS,
    LINE_KEYS,
)

#: A parsed claim envelope: the 17 keys of ``schemas/claim.schema.json`` in order.
Envelope = dict[str, Any]

#: JSON text convention of the pack data (``data/*/claims.jsonl``): UTF-8, no
#: ASCII escaping, stdlib ``", "`` / ``": "`` separators.
JSON_ENSURE_ASCII: Final = False

__all__ = [
    "ARRAY_CONTAINER_KEYS",
    "CHILD_KEYS",
    "JSON_ENSURE_ASCII",
    "SINGLE_CONTAINER_KEYS",
    "Envelope",
    "dump_envelope",
]

#: Envelope container key -> its nested contract keys, in contract order
#: (``schemas/claim.schema.json`` and the pack transport validator agree).
CHILD_KEYS: Final[Mapping[str, tuple[str, ...]]] = {
    "coverage": COVERAGE_KEYS,
    "lines": LINE_KEYS,
    "authorizations": AUTHORIZATION_KEYS,
    "attachments": ATTACHMENT_KEYS,
}

#: ``coverage`` is one object; the other three containers are arrays — the arity the
#: CSV join (one coverage row per claim) and the FHIR projection both rely on.
SINGLE_CONTAINER_KEYS: Final = ("coverage",)
ARRAY_CONTAINER_KEYS: Final = tuple(key for key in CHILD_KEYS if key not in SINGLE_CONTAINER_KEYS)


def dump_envelope(record: Mapping[str, Any]) -> str:
    """Serialize ``record`` exactly as ``json.dumps(record, ensure_ascii=False)``.

    Identical to the stdlib encoder for ``None``, ``bool``, ``int``, ``float``,
    ``str``, mappings and sequences — including the string escaping rules — with
    one addition: a :class:`~decimal.Decimal` is written as its exact literal
    instead of being lost through binary float. Keys are emitted in mapping order,
    which for an envelope is the order of :data:`claimguard.edu.envelope.ENVELOPE_KEYS`.
    """
    return _render(record)


def _render(value: Any) -> str:
    """Render one JSON value (see :func:`dump_envelope`)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return json.dumps(value)
    if isinstance(value, str):
        return _render_text(value)
    if isinstance(value, Mapping):
        items = cast("Mapping[str, Any]", value)
        pairs = ", ".join(f"{_render_text(key)}: {_render(item)}" for key, item in items.items())
        return "{" + pairs + "}"
    if isinstance(value, Sequence):
        items = cast("Sequence[Any]", value)
        return "[" + ", ".join(_render(item) for item in items) + "]"
    raise TypeError(f"not JSON-serializable: {type(value).__name__}")


def _render_text(text: str) -> str:
    """Render a JSON string (and therefore a JSON object key)."""
    return json.dumps(text, ensure_ascii=JSON_ENSURE_ASCII)
