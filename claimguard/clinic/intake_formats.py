"""Bounded, evidence-preserving normalization for the reviewer intake UI.

FHIR R4 in the teaching pack intentionally omits eleven envelope paths. A
complete sidecar is required for the 15-rule engine, and every path projected
from FHIR is checked against it before the sidecar can become an engine input.

The pack accepts three encodings of the same claim, and a reviewer uploading one
should not have to know which it is. :func:`detect_format` reads the payload and
says which encoding it *is*, on stated evidence, and - when it is none of them or
an incomplete one - says exactly what is wrong rather than making the reviewer
compare the payload against the contract by eye. Nothing here guesses: a payload
is only ever called a format when the payload itself carries that format's
marker, and every failure path returns a diagnosis instead of raising, so the
intake job records a reason a human can act on.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final, cast

from claimguard.edu.envelope import ENVELOPE_KEYS, TransportError, validate_transport
from claimguard.edu.intake import dump_envelope
from claimguard.edu.intake.csv_source import COLUMNS, CsvIntakeError, read_csv_files
from claimguard.edu.intake.fhir_source import (
    UNSUPPORTED_FIELDS,
    FhirIntakeError,
    project_bundle,
)


class IntakeNormalizationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def normalize_csv_package(files: Mapping[str, str]) -> dict[str, Any]:
    try:
        claims = read_csv_files(files)
        if len(claims) != 1:
            raise IntakeNormalizationError(
                "csv_claim_count",
                "Upload one claim at a time; claims.csv must contain exactly one data row.",
            )
        claim = json.loads(dump_envelope(claims[0]))
        validate_transport(claim)
        return claim
    except (CsvIntakeError, TransportError) as exc:
        raise IntakeNormalizationError("invalid_csv_package", str(exc)) from exc


def normalize_fhir_with_sidecar(
    bundle: dict[str, Any], sidecar: dict[str, Any] | None
) -> dict[str, Any]:
    if sidecar is None:
        raise IntakeNormalizationError(
            "fhir_requires_sidecar",
            "This FHIR teaching bundle omits authorization details, stable line IDs and notes. "
            "Upload its full normalized sidecar; FHIR facts will be compared before checking.",
        )
    try:
        projection = project_bundle(bundle).envelope
        validate_transport(sidecar)
    except (FhirIntakeError, TransportError) as exc:
        raise IntakeNormalizationError("invalid_fhir_package", str(exc)) from exc
    _assert_same_projection(projection, sidecar, "")
    return sidecar


def _assert_same_projection(projected: Any, supplied: Any, path: str) -> None:
    if isinstance(projected, Mapping):
        if not isinstance(supplied, Mapping):
            raise _mismatch(path)
        # The parameters arrive as `Any` (they walk parsed JSON of unknown shape), so the
        # isinstance check above is what establishes the mapping; name the element types
        # explicitly rather than letting them stay unknown to the type checker.
        projected_map = cast("Mapping[str, Any]", projected)
        supplied_map = cast("Mapping[str, Any]", supplied)
        for key, value in projected_map.items():
            _assert_same_projection(value, supplied_map.get(key), f"{path}/{key}")
    elif isinstance(projected, list):
        projected_list = cast("list[Any]", projected)
        supplied_list = cast("list[Any]", supplied) if isinstance(supplied, list) else None
        if supplied_list is None or len(projected_list) != len(supplied_list):
            raise _mismatch(path)
        for index, value in enumerate(projected_list):
            _assert_same_projection(value, supplied_list[index], f"{path}/{index}")
    elif (
        isinstance(projected, Decimal)
        and isinstance(supplied, (int, float, Decimal))
        and not isinstance(supplied, bool)
    ):
        if projected != Decimal(str(supplied)):
            raise _mismatch(path)
    elif projected != supplied:
        raise _mismatch(path)


def _mismatch(path: str) -> IntakeNormalizationError:
    return IntakeNormalizationError(
        "fhir_sidecar_mismatch", f"FHIR and sidecar disagree at {path or '/'}"
    )


# ---------------------------------------------------------------------------
# Undeclared-payload detection
#
# Three encodings, three markers, and nothing else is accepted: a JSON object
# that says ``resourceType: Bundle`` is FHIR, a JSON object whose key set is
# exactly the envelope contract is an envelope, and a mapping keyed by the five
# CSV filenames is a CSV package. The markers are the payload's own bytes, so
# the verdict is reproducible and independent of dict ordering; a payload that
# carries no marker is reported as UNKNOWN with the keys it lacks, never coerced
# into the nearest format.
# ---------------------------------------------------------------------------


class DetectedFormat(StrEnum):
    """Which of the pack's three public intake encodings a payload is written in."""

    ENVELOPE_JSON = "envelope_json"
    FHIR_BUNDLE = "fhir_bundle"
    CSV_PACKAGE = "csv_package"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IntakeDiagnosis:
    """What an undeclared payload *is*, and what is wrong with it.

    ``reasons`` is evidence - the marker that decided the verdict - while
    ``problems`` is the reviewer's to-do list. The two are separate because a
    payload can be identified with certainty and still be unusable (a FHIR bundle
    that needs its sidecar, a CSV package missing a file), and a reviewer needs
    to see both statements rather than one averaged sentence.
    """

    format: DetectedFormat
    confident: bool
    reasons: tuple[str, ...]
    problems: tuple[str, ...]


#: The relational files of a CSV package, in the order the converter joins them.
CSV_FILES: Final = tuple(COLUMNS)

#: Keys that may wrap a full envelope in transit; ``WorkspaceStore`` unwraps ``claim``.
_WRAPPER_KEYS: Final = ("claim", "envelope")

#: Names a message lists before it stops and counts the rest.
_MAX_NAMES: Final = 5

_ENVELOPE_REASON: Final = (
    f"the object carries exactly the {len(ENVELOPE_KEYS)} keys of the normalized envelope contract"
)


def detect_format(
    payload: str | bytes | Mapping[str, Any],
    *,
    filenames: Sequence[str] = (),
) -> IntakeDiagnosis:
    """Identify an undeclared intake payload and report what is wrong with it.

    ``payload`` is JSON text, its bytes, or the already-parsed object; for a CSV
    package it is the ``filename -> content`` mapping the intake form collects.
    ``filenames`` is the reviewer's upload name(s), used only as a hint when the
    text turns out not to be JSON at all.

    Detection never raises: an ambiguous payload comes back as
    :attr:`DetectedFormat.UNKNOWN` with :attr:`IntakeDiagnosis.problems` naming
    what is missing. ``confident`` means the payload carries its format's marker
    completely - not that the payload is valid, which the problems report.
    """
    return _diagnose_payload(payload, tuple(filenames))


def _diagnose_payload(raw: object, filenames: tuple[str, ...]) -> IntakeDiagnosis:
    """Dispatch on what the payload actually is; an unexpected type is diagnosed, not raised."""
    if isinstance(raw, Mapping):
        return _diagnose_object(cast("Mapping[str, Any]", raw))
    if isinstance(raw, (str, bytes)):
        return _diagnose_text(raw, filenames)
    return _unrecognized(raw)


def _unrecognized(raw: object) -> IntakeDiagnosis:
    """Diagnose a payload of a type the intake form never sends, instead of raising."""
    return _unknown(
        (f"the payload is a {type(raw).__name__}, not JSON text or a file mapping",),
        (
            "expected JSON text, a JSON object, or a filename -> content mapping; "
            f"got {type(raw).__name__}",
        ),
    )


def _diagnose_text(text: str | bytes, filenames: tuple[str, ...]) -> IntakeDiagnosis:
    """Diagnose JSON text (or its bytes); a non-JSON document is UNKNOWN or a CSV hint."""
    if isinstance(text, bytes):
        try:
            decoded = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            return _unknown(
                ("the payload is bytes that are not UTF-8 text",),
                (f"decoding failed at byte {exc.start}: {exc.reason}",),
            )
    else:
        decoded = text
    try:
        parsed: object = json.loads(decoded)
    except json.JSONDecodeError as exc:
        return _diagnose_unparsed(filenames, exc)
    if isinstance(parsed, Mapping):
        return _diagnose_object(cast("Mapping[str, Any]", parsed))
    return _unknown(
        (f"the JSON text parses to a {type(parsed).__name__}, not a JSON object",),
        (
            "a claim payload must be a JSON object (a normalized envelope or a FHIR Bundle); "
            f"this one parses to a {type(parsed).__name__}",
        ),
    )


def _diagnose_unparsed(filenames: tuple[str, ...], exc: json.JSONDecodeError) -> IntakeDiagnosis:
    """A document that is not JSON: a CSV upload by name, or UNKNOWN with the parse error."""
    csv_names = tuple(name for name in filenames if _is_csv_name(name))
    if csv_names:
        supplied = frozenset(csv_names)
        missing = tuple(name for name in CSV_FILES if name not in supplied)
        return IntakeDiagnosis(
            DetectedFormat.CSV_PACKAGE,
            not missing,
            (f"the document is not JSON, but the uploaded name(s) are CSV: {_names(csv_names)}",),
            tuple(f"required CSV file is absent: {name}" for name in missing),
        )
    return _unknown(
        ("the document is not JSON text, so it is neither an envelope nor a FHIR Bundle",),
        (f"JSON parsing failed: {exc.msg} (line {exc.lineno}, column {exc.colno})",),
    )


def _diagnose_object(mapping: Mapping[str, Any]) -> IntakeDiagnosis:
    """Diagnose a parsed JSON object, or the filename -> content mapping of a package."""
    keys = frozenset(str(key) for key in mapping)
    if mapping.get("resourceType") == "Bundle":
        return _diagnose_fhir(mapping)
    if keys == frozenset(ENVELOPE_KEYS):
        return _diagnose_envelope(mapping, _ENVELOPE_REASON)
    wrapped = _wrapped_envelope(mapping)
    if wrapped is not None:
        key, inner = wrapped
        return _diagnose_envelope(inner, f"the single {key!r} key wraps a full envelope")
    if any(_is_csv_name(key) for key in keys):
        return _diagnose_csv(mapping)
    if keys & frozenset(ENVELOPE_KEYS):
        return _diagnose_near_envelope(keys)
    missing = tuple(key for key in ENVELOPE_KEYS if key not in keys)
    return _unknown(
        (
            "the object's keys are neither an envelope's nor a FHIR Bundle's: "
            f"{_names(tuple(sorted(keys)))}",
            f"the envelope contract needs {len(ENVELOPE_KEYS)} keys and none of them is present "
            f"(missing: {_names(missing)})",
            'the object has no "resourceType" and names no CSV file',
        ),
        (
            "the payload matches no supported intake format: declare the format, or upload a "
            "normalized envelope, a FHIR Bundle, or the five CSV files",
        ),
    )


def _diagnose_envelope(mapping: Mapping[str, Any], reason: str) -> IntakeDiagnosis:
    """A key set that *is* the envelope contract; still report transport defects."""
    problems: list[str] = []
    try:
        validate_transport(mapping)
    except TransportError as exc:
        problems.append(f"the envelope transport contract rejects this payload: {exc}")
    return IntakeDiagnosis(DetectedFormat.ENVELOPE_JSON, True, (reason,), tuple(problems))


def _diagnose_near_envelope(keys: frozenset[str]) -> IntakeDiagnosis:
    """An envelope-shaped object that misses the contract: UNKNOWN, keys named exactly."""
    missing = tuple(key for key in ENVELOPE_KEYS if key not in keys)
    unexpected = tuple(sorted(key for key in keys if key not in frozenset(ENVELOPE_KEYS)))
    return IntakeDiagnosis(
        DetectedFormat.UNKNOWN,
        False,
        (
            f"the object shares {len(ENVELOPE_KEYS) - len(missing)} of the {len(ENVELOPE_KEYS)} "
            "envelope keys, so it is not the transport contract, and it carries no "
            '"resourceType": Bundle',
            "the exact keys to add or rename are listed in the problems",
        ),
        (
            *(f"missing envelope key: {key}" for key in missing),
            *(f"unexpected key: {key}" for key in unexpected),
        ),
    )


def _diagnose_fhir(bundle: Mapping[str, Any]) -> IntakeDiagnosis:
    """A Bundle is FHIR; say which envelope paths its sidecar still has to supply."""
    bundle_type = bundle.get("type")
    suffix = f" of type {bundle_type!r}" if isinstance(bundle_type, str) else ""
    return IntakeDiagnosis(
        DetectedFormat.FHIR_BUNDLE,
        True,
        (
            f'the object declares "resourceType": "Bundle"{suffix}',
            f"a pack FHIR bundle omits the {len(UNSUPPORTED_FIELDS)} envelope paths listed below",
        ),
        (
            "upload the bundle with its full normalized sidecar: a bundle alone cannot pass the "
            "15-rule engine",
            *(
                f"needs the sidecar: {field.path} - {_brief(field.reason)}"
                for field in UNSUPPORTED_FIELDS
            ),
        ),
    )


def _diagnose_csv(mapping: Mapping[str, Any]) -> IntakeDiagnosis:
    """A filename-keyed mapping is a CSV package; report the files it is missing."""
    present = tuple(name for name in CSV_FILES if name in mapping)
    missing = tuple(name for name in CSV_FILES if name not in mapping)
    extra = tuple(sorted(str(name) for name in mapping if name not in frozenset(CSV_FILES)))
    return IntakeDiagnosis(
        DetectedFormat.CSV_PACKAGE,
        not missing,
        (
            f"the mapping is keyed by CSV filenames: "
            f"{_names(present) or 'none of the required five'}",
            f"a complete package is exactly: {', '.join(CSV_FILES)}",
        ),
        (
            *(f"required CSV file is absent: {name}" for name in missing),
            *(f"unexpected file in the package: {name}" for name in extra),
            *(
                f"the content of {name} must be text, not {type(mapping[name]).__name__}"
                for name in present
                if not isinstance(mapping[name], str)
            ),
        ),
    )


def _wrapped_envelope(mapping: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]] | None:
    """The single ``claim``/``envelope`` wrapper around a full envelope, when there is one."""
    if len(mapping) != 1:
        return None
    key = next(iter(mapping))
    if key not in _WRAPPER_KEYS:
        return None
    inner = mapping[key]
    if not isinstance(inner, Mapping):
        return None
    inner_map = cast("Mapping[str, Any]", inner)
    if frozenset(str(entry) for entry in inner_map) == frozenset(ENVELOPE_KEYS):
        return key, inner_map
    return None


def _is_csv_name(name: str) -> bool:
    """True for a filename the reviewer would upload as part of a CSV package."""
    return name.lower().endswith(".csv")


def _names(names: Sequence[str], limit: int = _MAX_NAMES) -> str:
    """A comma-joined name list, counting the tail it did not print."""
    hidden = len(names) - limit
    listed = ", ".join(names[:limit])
    return listed if hidden <= 0 else f"{listed} and {hidden} more"


def _brief(text: str, limit: int = 140) -> str:
    """The first sentence of a long justification, capped for a reviewer-facing message."""
    sentence = text.split(". ", 1)[0].strip().rstrip(".")
    return sentence if len(sentence) <= limit else f"{sentence[: limit - 3].rstrip()}..."


def _unknown(reasons: tuple[str, ...], problems: tuple[str, ...]) -> IntakeDiagnosis:
    """A diagnosis that names no format - never a guess at the nearest one."""
    return IntakeDiagnosis(DetectedFormat.UNKNOWN, False, reasons, problems)
