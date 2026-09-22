"""Evidence pointers: RFC 6901 resolution over the ORIGINAL claim envelope.

The mentor scorer re-resolves every pointer against the original claim and
requires equality (``src/evaluate.py::index``):

    if pointer(c, e['path']) != e['value']: raise ValueError('Evidence value mismatch')

So evidence is built by *resolving* the pointer and storing the object found —
the observed value is never re-typed, re-rounded or re-serialized
(docs/04_Rulebook.md:15; docs/03_Data_Dictionary.md, "Result contract").

Pointer conventions of the pack: zero-based array indices for line/record
positions (``/lines/0/service_date``), while ``affected_line_ids`` carry the
stable ``L1``/``L2`` identifiers (docs/03_Data_Dictionary.md, "Result contract").
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, cast


class EvidenceError(ValueError):
    """A pointer is malformed, does not resolve, or its value does not match."""


def parse_pointer(pointer: str) -> tuple[str, ...]:
    """Split an RFC 6901 pointer into unescaped reference tokens."""
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise EvidenceError(f"Evidence path must start with '/': {pointer!r}")
    return tuple(_unescape(token) for token in pointer.split("/")[1:])


def _unescape(token: str) -> str:
    """RFC 6901 §4: ``~1`` is ``/`` and ``~0`` is ``~`` (in that order)."""
    return token.replace("~1", "/").replace("~0", "~")


def resolve(document: Any, pointer: str) -> Any:
    """Resolve ``pointer`` against ``document`` and return the exact value found.

    Raises :class:`EvidenceError` when a token is absent, an array index is not
    a canonical non-negative integer, or the pointer walks into a scalar.
    """
    current: Any = document
    for token in parse_pointer(pointer):
        if isinstance(current, Mapping):
            mapping = cast("Mapping[str, Any]", current)
            if token not in mapping:
                raise EvidenceError(f"Pointer {pointer!r} does not resolve: missing {token!r}")
            current = mapping[token]
        elif isinstance(current, list):
            items = cast("list[Any]", current)
            index = _array_index(token, pointer)
            if index >= len(items):
                raise EvidenceError(
                    f"Pointer {pointer!r} does not resolve: index {index} out of range"
                )
            current = items[index]
        else:
            raise EvidenceError(f"Pointer {pointer!r} does not resolve: {token!r} into a scalar")
    return current


def _array_index(segment: str, pointer: str) -> int:
    """Validate the RFC 6901 array-index segment (``0`` or ``[1-9][0-9]*``)."""
    if segment.isdigit() and (segment == "0" or not segment.startswith("0")):
        return int(segment)
    raise EvidenceError(f"Pointer {pointer!r} has an invalid array index {segment!r}")


def make_entry(document: Any, pointer: str) -> dict[str, Any]:
    """Build one ``{"path": ..., "value": ...}`` evidence entry."""
    return {"path": pointer, "value": resolve(document, pointer)}


def build_evidence(
    document: Any, pointers: Iterable[str], *, require: bool = True
) -> list[dict[str, Any]]:
    """Build de-duplicated evidence entries, preserving the pointer order given.

    ``require`` enforces the pack rule that every implemented result carries at
    least one evidence entry (docs/07_Evaluation_and_Acceptance.md, acceptance).
    """
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pointer in pointers:
        if not pointer or pointer in seen:
            continue
        seen.add(pointer)
        entries.append(make_entry(document, pointer))
    if require and not entries:
        raise EvidenceError("At least one evidence pointer is required")
    return entries


def values_match(observed: Any, claimed: Any) -> bool:
    """Compare an observed value with a claimed evidence value.

    The pack scorer compares with ``!=``. This helper is deliberately stricter
    on JSON *type* (``1`` is not ``1.0``, ``True`` is not ``1``) because evidence
    is built from the object that resolution returned — a type difference means
    the value was rewritten somewhere, which is exactly the defect this guard
    exists to catch (pack conformance is preserved: any value produced by
    :func:`build_evidence` compares equal).
    """
    if isinstance(observed, bool) or isinstance(claimed, bool):
        return observed is claimed
    if type(observed) is not type(claimed):
        return False
    if isinstance(observed, list) and isinstance(claimed, list):
        left = cast("list[Any]", observed)
        right = cast("list[Any]", claimed)
        return len(left) == len(right) and all(
            values_match(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(observed, Mapping) and isinstance(claimed, Mapping):
        left_map = cast("Mapping[str, Any]", observed)
        right_map = cast("Mapping[str, Any]", claimed)
        return set(left_map) == set(right_map) and all(
            values_match(left_map[key], right_map[key]) for key in left_map
        )
    return bool(observed == claimed)


def verify_evidence(document: Any, entries: Iterable[Mapping[str, Any]]) -> None:
    """Re-resolve every evidence entry against ``document``; raise on mismatch."""
    for entry in entries:
        if set(entry) != {"path", "value"}:
            raise EvidenceError("Evidence entries must be {'path': ..., 'value': ...}")
        path = entry["path"]
        if not isinstance(path, str):
            raise EvidenceError("Evidence path must be a string")
        observed = resolve(document, path)
        if not values_match(observed, entry["value"]):
            raise EvidenceError(f"Evidence value mismatch at {path!r}: {entry['value']!r}")
