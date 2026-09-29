"""P0 telemetry safety — defensive sanitization (docs/20 §13.6).

Guarantees:
1. Sanitization copies the input, keeps only allow-listed fields with valid
   values, and drops forbidden/unknown/free-text fields.
2. correlation_id / request_id are retained only when a valid UUID or exactly
   32 lowercase hex characters; otherwise they are omitted.
3. Sanitizers never raise (telemetry is fail-open) and never mutate input.
4. No PII / PHI / free text leaks into the sanitized output.
"""

from __future__ import annotations

import copy
import uuid

import pytest
from claimguard.ops.redaction import sanitize_metric_labels, sanitize_telemetry_record

SAFE_LABELS: dict[str, object] = {
    "service": "claimguard",
    "component": "rule_engine",
    "route_template": "/v1/runs/{run_id}/decisions",
    "method": "POST",
    "status_class": "4xx",
    "queue_job_category": "document_ingest",
    "integration_category": "velodoc_api",
}

SAFE_RECORD: dict[str, object] = {
    "timestamp": "2026-09-28T10:00:00.123456+04:00",
    "level": "info",
    "service": "claimguard",
    "component": "rule_engine",
    "route_template": "/v1/claims/{claim_id}",
    "method": "POST",
    "status_class": "4xx",
    "duration_ms": 150.5,
    "error_category": "evidence_unresolvable",
    "queue_job_category": "document_ingest",
    "integration_category": "velodoc_api",
    "correlation_id": "9f3a8e5b-1b2c-4d3e-8f90-abcdef123456",
    "request_id": "9f3a8e5b1b2c4d3e8f90abcdef123456",
    "version": "0.1.0",
}


# ---------------------------------------------------------------------------
# Metric labels
# ---------------------------------------------------------------------------


def test_sanitize_metric_labels_keeps_only_allowed_labels() -> None:
    dirty = dict(SAFE_LABELS)
    dirty.update(
        {
            "claim_id": "CLM-0042",
            "tenant_id": "ten-001",
            "email": "ops@example.com",
            "message": "boom",
            "correlation_id": "9f3a8e5b1b2c4d3e8f90abcdef123456",
            "level": "info",  # valid record field, NOT a metric label
            "foo": "bar",
        }
    )
    safe = sanitize_metric_labels(dirty)
    assert safe == SAFE_LABELS


def test_sanitize_metric_labels_drops_unsafe_values() -> None:
    dirty = {
        "service": "CLM-0042",  # visible claim id
        "component": "sara.mansour@gmail.com",  # email
        "route_template": "/v1/claims/CLM-0042",  # concrete route
        "method": "FIND",
        "status_class": "404",
    }
    assert sanitize_metric_labels(dirty) == {}


def test_sanitize_metric_labels_never_raises() -> None:
    dirty: dict[str, object] = {"service": 42, "component": None, "method": ["GET"]}
    assert sanitize_metric_labels(dirty) == {}


def test_sanitize_metric_labels_does_not_mutate_input() -> None:
    dirty = dict(SAFE_LABELS)
    dirty["claim_id"] = "CLM-0042"
    dirty["nested"] = {"patient": {"name": "Sara Mansour"}}
    before = copy.deepcopy(dirty)
    sanitize_metric_labels(dirty)
    assert dirty == before


# ---------------------------------------------------------------------------
# Structured telemetry records
# ---------------------------------------------------------------------------


def test_sanitize_telemetry_record_preserves_safe_fields() -> None:
    assert sanitize_telemetry_record(SAFE_RECORD) == SAFE_RECORD


def test_sanitize_telemetry_record_drops_forbidden_fields() -> None:
    dirty = dict(SAFE_RECORD)
    dirty.update(
        {
            "message": "coverage ended before service",
            "exception": "TypeError",
            "error_message": "boom",
            "body": '{"patient": {"name": "Sara Mansour"}}',
            "request_body": "raw",
            "response_body": "raw",
            "header": "Authorization: Bearer abc123",
            "headers": {"x-auth": "Bearer abc123"},
            "cookie": "session=eyJhbGciOi",
            "cookies": "session=eyJhbGciOi",
            "query": "memberId=MBR-001",
            "query_string": "diagnosis=lumbar+disc+herniation",
            "url": "/v1/claims/CLM-0042",
            "sql": "SELECT * FROM patients WHERE mrn = 'MRN-7731'",
            "prompt": "Summarize clinical notes for Sara Mansour",
            "clinical": "diagnosis: lumbar disc herniation",
            "diagnosis": "lumbar disc herniation",
            "narrative": "Coverage ended before the MRI was performed.",
            "patient_name": "Sara Mansour",
            "note": "call patient back",
            "claim_id": "CLM-0042",
            "run_id": "run-9f3a8e5b",
            "tenant_id": "ten-001",
            "email": "sara.mansour@example.com",
            "user_id": "user-42",
        }
    )
    safe = sanitize_telemetry_record(dirty)
    assert safe == SAFE_RECORD


def test_sanitize_telemetry_record_retains_valid_ids() -> None:
    record = {
        "correlation_id": str(uuid.uuid4()),
        "request_id": "9f3a8e5b1b2c4d3e8f90abcdef123456",
    }
    safe = sanitize_telemetry_record(record)
    assert safe["correlation_id"] == str(uuid.UUID(record["correlation_id"]))
    assert safe["request_id"] == "9f3a8e5b1b2c4d3e8f90abcdef123456"


@pytest.mark.parametrize(
    "value",
    [
        "9F3A8E5B1B2C4D3E8F90ABCDEF123456",  # uppercase 32-hex — omitted
        "abc",
        "CLM-0042",
        "9f3a8e5b-1b2c-4d3e-8f90-abcdef12345",  # truncated UUID
        "not-an-id",
        "",
    ],
)
def test_sanitize_telemetry_record_omits_unsafe_ids(value: str) -> None:
    safe = sanitize_telemetry_record({"correlation_id": value, "request_id": value})
    assert "correlation_id" not in safe
    assert "request_id" not in safe


def test_sanitize_telemetry_record_drops_out_of_range_values() -> None:
    dirty: dict[str, object] = {
        "duration_ms": -5,
        "level": "URGENT",
        "timestamp": "yesterday",
        "service": "a" * 65,
        "version": "v1.2.3",  # valid slug, retained as control
    }
    safe = sanitize_telemetry_record(dirty)
    assert safe == {"version": "v1.2.3"}


def test_sanitize_telemetry_record_never_raises() -> None:
    dirty: dict[str, object] = {
        "service": object(),
        "duration_ms": "fast",
        "correlation_id": None,
        "level": 42,
    }
    assert sanitize_telemetry_record(dirty) == {}


def test_sanitize_telemetry_record_does_not_mutate_input() -> None:
    dirty = dict(SAFE_RECORD)
    dirty["message"] = "boom"
    dirty["nested"] = {"patient": {"name": "Sara Mansour"}}
    before = copy.deepcopy(dirty)
    sanitize_telemetry_record(dirty)
    assert dirty == before


# ---------------------------------------------------------------------------
# PII / free-text leakage
# ---------------------------------------------------------------------------


def test_no_pii_or_free_text_leakage() -> None:
    """A record stuffed with PHI, free text, and smeared identifiers stays clean.

    Allow-listed fields that smuggle PII (service="Sara Mansour",
    component="mrn-7731", route_template with a concrete id) must also be
    dropped by value validation — the canary strings never appear in output.
    """
    dirty: dict[str, object] = {
        "message": "patient Sara Mansour MRN-7731 needs an MRI",
        "exception": "TypeError at /claims/CLM-0042",
        "body": '{"patient": {"name": "Sara Mansour", "mrn": "MRN-7731"}}',
        "headers": "Authorization: Bearer abc123",
        "cookie": "session=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "query": "memberId=MBR-001&diagnosis=lumbar+disc+herniation",
        "sql": "SELECT * FROM patients WHERE mrn = 'MRN-7731'",
        "prompt": "Summarize the clinical notes for Sara Mansour",
        "clinical": "diagnosis: lumbar disc herniation",
        "claim_id": "CLM-0042",
        "run_id": "run-9f3a8e5b",
        "tenant_id": "ten-001",
        "email": "sara.mansour@example.com",
        "user_id": "user-42",
        # allow-listed keys carrying PII — dropped by value validation
        "service": "Sara Mansour",
        "component": "mrn-7731",
        "route_template": "/v1/claims/CLM-0042",
        "level": "error",  # clean, retained as a control
    }
    safe = sanitize_telemetry_record(dirty)
    assert safe == {"level": "error"}

    serialized = " ".join(f"{key}={value}" for key, value in safe.items())
    for canary in (
        "Sara",
        "Mansour",
        "MRN-7731",
        "lumbar",
        "Bearer",
        "session=",
        "SELECT",
        "CLM-0042",
        "MBR-001",
        "abc123",
    ):
        assert canary not in serialized
