"""The three public demo formats must normalize without hidden input repair."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from claimguard.clinic.intake_formats import (
    IntakeNormalizationError,
    normalize_fhir_with_sidecar,
)
from claimguard.edu.envelope import validate_transport
from claimguard.edu.intake import dump_envelope
from claimguard.edu.intake.csv_source import read_csv_files, read_csv_split

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "phase1"


def test_json_sample_is_full_normalized_envelope() -> None:
    claim = json.loads((EXAMPLES / "envelope.json").read_text(encoding="utf-8"))
    validate_transport(claim)
    assert claim["coverage"]["end_date"] < claim["lines"][0]["service_date"]


def test_csv_sample_can_be_normalized_without_temp_files() -> None:
    files = {
        path.name: path.read_text(encoding="utf-8") for path in (EXAMPLES / "csv").glob("*.csv")
    }
    assert read_csv_files(files) == read_csv_split(EXAMPLES / "csv")
    assert len(read_csv_files(files)) == 1
    validate_transport(json.loads(dump_envelope(read_csv_files(files)[0])))


def test_fhir_sample_reconciles_only_with_verified_sidecar() -> None:
    bundle = json.loads((EXAMPLES / "fhir-bundle.json").read_text(encoding="utf-8"))
    sidecar = json.loads((EXAMPLES / "fhir-sidecar.json").read_text(encoding="utf-8"))
    claim = normalize_fhir_with_sidecar(bundle, sidecar)
    validate_transport(claim)
    assert claim["claim_id"] == "PHASE1-FHIR-001"

    sidecar["coverage"]["end_date"] = "2026-12-31"
    with pytest.raises(IntakeNormalizationError, match="coverage/end_date"):
        normalize_fhir_with_sidecar(bundle, sidecar)


def test_fhir_without_sidecar_is_not_silently_completed() -> None:
    bundle = json.loads((EXAMPLES / "fhir-bundle.json").read_text(encoding="utf-8"))
    with pytest.raises(IntakeNormalizationError, match="sidecar"):
        normalize_fhir_with_sidecar(bundle, None)
