"""An undeclared payload is identified from its own bytes, or reported precisely.

Every case here is offline and deterministic: the detector reads the three public
demo payloads, the CSV package they ship with, and a set of near-misses. The
near-misses matter as much as the hits - a reviewer who uploads the wrong thing
gets the exact keys that are missing or misnamed, never a guess at the nearest
supported format.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from claimguard.clinic.intake_formats import (
    CSV_FILES,
    DetectedFormat,
    IntakeDiagnosis,
    detect_format,
)
from claimguard.edu.envelope import ENVELOPE_KEYS
from claimguard.edu.intake.fhir_source import UNSUPPORTED_FIELDS

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "phase1"


def _json(name: str) -> dict[str, Any]:
    # The three demo payloads are JSON objects; the cast names that shape.
    return cast("dict[str, Any]", json.loads((EXAMPLES / name).read_text(encoding="utf-8")))


def _csv_files() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8") for path in (EXAMPLES / "csv").glob("*.csv")
    }


def test_normalized_envelope_is_recognized_confidently() -> None:
    diagnosis = detect_format(_json("envelope.json"))
    assert diagnosis.format is DetectedFormat.ENVELOPE_JSON
    assert diagnosis.confident
    assert diagnosis.problems == ()
    assert "17 keys" in diagnosis.reasons[0]


def test_envelope_also_detected_through_json_text_bytes_and_wrapper() -> None:
    envelope = _json("envelope.json")
    text = json.dumps(envelope)
    for payload in (text, text.encode("utf-8"), {"claim": envelope}, {"envelope": envelope}):
        diagnosis = detect_format(payload)
        assert diagnosis.format is DetectedFormat.ENVELOPE_JSON, payload
        assert diagnosis.confident, payload
        assert diagnosis.problems == (), payload


def test_envelope_with_a_transport_defect_is_confident_but_reports_the_defect() -> None:
    envelope = _json("envelope.json")
    envelope["submission_date"] = "not-a-date"
    diagnosis = detect_format(envelope)
    assert diagnosis.format is DetectedFormat.ENVELOPE_JSON
    assert diagnosis.confident
    assert len(diagnosis.problems) == 1
    assert "submission date" in diagnosis.problems[0]


def test_fhir_bundle_names_every_path_that_needs_the_sidecar() -> None:
    diagnosis = detect_format(_json("fhir-bundle.json"))
    assert diagnosis.format is DetectedFormat.FHIR_BUNDLE
    assert diagnosis.confident
    assert diagnosis.reasons[0] == (
        'the object declares "resourceType": "Bundle" of type \'collection\''
    )
    assert len(diagnosis.problems) == len(UNSUPPORTED_FIELDS) + 1
    for field in UNSUPPORTED_FIELDS:
        assert any(field.path in problem for problem in diagnosis.problems), field.path
    assert any("sidecar" in problem for problem in diagnosis.problems)


def test_csv_package_of_five_files_is_recognized_confidently() -> None:
    diagnosis = detect_format(_csv_files())
    assert diagnosis.format is DetectedFormat.CSV_PACKAGE
    assert diagnosis.confident
    assert diagnosis.problems == ()
    assert len(CSV_FILES) == 5


def test_csv_package_missing_a_file_names_that_file() -> None:
    files = _csv_files()
    del files["lines.csv"]
    diagnosis = detect_format(files)
    assert diagnosis.format is DetectedFormat.CSV_PACKAGE
    assert not diagnosis.confident
    assert diagnosis.problems == ("required CSV file is absent: lines.csv",)


def test_csv_package_with_an_extra_file_reports_it_without_losing_the_format() -> None:
    files = _csv_files()
    files["notes.txt"] = "unrelated"
    diagnosis = detect_format(files)
    assert diagnosis.format is DetectedFormat.CSV_PACKAGE
    assert diagnosis.confident
    assert diagnosis.problems == ("unexpected file in the package: notes.txt",)


def test_csv_upload_reported_by_filename_when_the_document_is_not_json() -> None:
    diagnosis = detect_format("claim_id,patient_id\nC-1,P-1", filenames=("claims.csv", "lines.csv"))
    assert diagnosis.format is DetectedFormat.CSV_PACKAGE
    assert not diagnosis.confident
    assert diagnosis.problems == (
        "required CSV file is absent: coverage.csv",
        "required CSV file is absent: authorizations.csv",
        "required CSV file is absent: attachments.csv",
    )


def test_near_miss_envelope_is_not_confident_and_names_the_exact_keys() -> None:
    envelope = _json("envelope.json")
    del envelope["invoice_number"]
    envelope["currancy"] = envelope.pop("currency")
    diagnosis = detect_format(envelope)
    assert diagnosis.format is DetectedFormat.UNKNOWN
    assert not diagnosis.confident
    assert "missing envelope key: invoice_number" in diagnosis.problems
    assert "missing envelope key: currency" in diagnosis.problems
    assert "unexpected key: currancy" in diagnosis.problems
    assert "problems" in diagnosis.reasons[1]


def test_garbage_is_unknown_with_a_reason_and_never_raises() -> None:
    cases: list[object] = [
        "hello",
        "[1, 2, 3]",
        '{"foo": 1, "bar": 2}',
        b"\xff\xfe",
        cast(Any, 42),
    ]
    for payload in cases:
        diagnosis = detect_format(cast(Any, payload))
        assert diagnosis.format is DetectedFormat.UNKNOWN, payload
        assert not diagnosis.confident, payload
        assert diagnosis.reasons, payload
        assert all(reason for reason in diagnosis.reasons), payload


def test_unrelated_object_reason_lists_the_missing_envelope_keys() -> None:
    diagnosis = detect_format({"alpha": 1, "beta": 2})
    assert diagnosis.format is DetectedFormat.UNKNOWN
    assert ENVELOPE_KEYS[0] in diagnosis.reasons[1]
    assert "matches no supported intake format" in diagnosis.problems[0]


def test_detection_is_stable_and_order_independent() -> None:
    envelope = _json("envelope.json")
    reversed_envelope = {key: envelope[key] for key in reversed(ENVELOPE_KEYS)}
    assert detect_format(envelope) == detect_format(envelope)
    assert detect_format(envelope) == detect_format(reversed_envelope)

    files = _csv_files()
    reversed_files = dict(reversed(list(files.items())))
    assert detect_format(files) == detect_format(files)
    assert detect_format(files) == detect_format(reversed_files)

    unrelated = {"alpha": 1, "beta": 2}
    assert detect_format(unrelated) == detect_format({"beta": 2, "alpha": 1})


def test_diagnosis_is_a_plain_frozen_dataclass() -> None:
    diagnosis = detect_format(_json("envelope.json"))
    assert isinstance(diagnosis, IntakeDiagnosis)
    assert isinstance(diagnosis.reasons, tuple)
    assert isinstance(diagnosis.problems, tuple)
