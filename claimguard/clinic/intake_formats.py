"""Bounded, evidence-preserving normalization for the reviewer intake UI.

FHIR R4 in the teaching pack intentionally omits eleven envelope paths. A
complete sidecar is required for the 15-rule engine, and every path projected
from FHIR is checked against it before the sidecar can become an engine input.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, cast

from claimguard.edu.envelope import TransportError, validate_transport
from claimguard.edu.intake import dump_envelope
from claimguard.edu.intake.csv_source import CsvIntakeError, read_csv_files
from claimguard.edu.intake.fhir_source import FhirIntakeError, project_bundle


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
