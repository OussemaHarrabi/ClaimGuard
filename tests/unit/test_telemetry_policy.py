"""P0 telemetry safety — the allow-list policy contract (docs/20 §13.6).

Guarantees:
1. The metric-label allow-list is exactly the seven low-cardinality dimensions
   and is immutable.
2. The structured telemetry field allow-list is exactly the fourteen fields and
   is a superset of the label allow-list.
3. Forbidden identifier keys (tenant_id, claim_id, run_id, user ids, emails)
   and correlation ids are rejected as metric labels.
4. Unknown keys, unsafe/identifier-like values, oversized values, and concrete
   route identifiers are rejected.
5. Validators never mutate their input.
"""

from __future__ import annotations

import uuid

import pytest
from claimguard.ops.telemetry_policy import (
    FORBIDDEN_FREETEXT_KEYS,
    FORBIDDEN_IDENTIFIER_KEYS,
    METRIC_LABEL_ALLOWLIST,
    TELEMETRY_FIELD_ALLOWLIST,
    TelemetryPolicyError,
    validate_metric_label,
    validate_metric_labels,
    validate_telemetry_field,
    validate_telemetry_fields,
)

VALID_LABELS: dict[str, object] = {
    "service": "claimguard",
    "component": "rule_engine",
    "route_template": "/v1/runs/{run_id}/decisions",
    "method": "POST",
    "status_class": "4xx",
    "queue_job_category": "document_ingest",
    "integration_category": "velodoc_api",
}

VALID_RECORD: dict[str, object] = {
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
# Allow-list contents and immutability
# ---------------------------------------------------------------------------


def test_metric_label_allowlist_is_exactly_the_seven_dimensions() -> None:
    assert (
        frozenset(
            {
                "service",
                "component",
                "route_template",
                "method",
                "status_class",
                "queue_job_category",
                "integration_category",
            }
        )
        == METRIC_LABEL_ALLOWLIST
    )


def test_telemetry_field_allowlist_is_exactly_the_fourteen_fields() -> None:
    assert (
        frozenset(
            {
                "timestamp",
                "level",
                "service",
                "component",
                "route_template",
                "method",
                "status_class",
                "duration_ms",
                "error_category",
                "queue_job_category",
                "integration_category",
                "correlation_id",
                "request_id",
                "version",
            }
        )
        == TELEMETRY_FIELD_ALLOWLIST
    )


def test_allowlists_are_immutable() -> None:
    with pytest.raises(AttributeError):
        METRIC_LABEL_ALLOWLIST.add("claim_id")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        TELEMETRY_FIELD_ALLOWLIST.add("message")  # type: ignore[attr-defined]


def test_label_allowlist_is_subset_of_field_allowlist() -> None:
    assert METRIC_LABEL_ALLOWLIST <= TELEMETRY_FIELD_ALLOWLIST


def test_forbidden_identifier_keys_disjoint_from_allowlists() -> None:
    assert FORBIDDEN_IDENTIFIER_KEYS.isdisjoint(METRIC_LABEL_ALLOWLIST)
    assert FORBIDDEN_IDENTIFIER_KEYS.isdisjoint(TELEMETRY_FIELD_ALLOWLIST)
    assert FORBIDDEN_FREETEXT_KEYS.isdisjoint(TELEMETRY_FIELD_ALLOWLIST)


def test_policy_error_is_a_value_error() -> None:
    assert issubclass(TelemetryPolicyError, ValueError)


# ---------------------------------------------------------------------------
# Metric labels — allowed
# ---------------------------------------------------------------------------


def test_valid_metric_labels_round_trip() -> None:
    assert validate_metric_labels(VALID_LABELS) == VALID_LABELS


def test_valid_metric_label_accepts_route_template_placeholders() -> None:
    for template in (
        "/v1/claims/{claim_id}",
        "/v1/queue/{job_id}/status",
        "/health",
        "/",
    ):
        assert validate_metric_label("route_template", template) == template


# ---------------------------------------------------------------------------
# Metric labels — rejected
# ---------------------------------------------------------------------------


def test_unknown_metric_label_rejected() -> None:
    with pytest.raises(TelemetryPolicyError):
        validate_metric_label("foo", "bar")
    with pytest.raises(TelemetryPolicyError):
        validate_metric_labels({"service": "claimguard", "foo": "bar"})


@pytest.mark.parametrize(
    "key",
    [
        "tenant_id",
        "claim_id",
        "run_id",
        "user_id",
        "member_id",
        "patient_id",
        "provider_id",
        "subscriber_id",
        "reviewer_id",
        "email",
        "user_email",
    ],
)
def test_forbidden_identifier_keys_rejected_as_metric_labels(key: str) -> None:
    with pytest.raises(TelemetryPolicyError):
        validate_metric_label(key, "abc")


def test_correlation_and_request_id_rejected_as_metric_labels() -> None:
    with pytest.raises(TelemetryPolicyError):
        validate_metric_label("correlation_id", "9f3a8e5b1b2c4d3e8f90abcdef123456")
    with pytest.raises(TelemetryPolicyError):
        validate_metric_label("request_id", "9f3a8e5b-1b2c-4d3e-8f90-abcdef123456")


@pytest.mark.parametrize(
    "value",
    [
        "CLM-0042",  # visible claim id (uppercase)
        "MBR-001",  # member id
        "Sara Mansour",  # patient name, free text with space
        "sara.mansour@gmail.com",  # email
        "9f3a8e5b1b2c4d3e8f90abcdef123456",  # 32-hex id
        "9f3a8e5b-1b2c-4d3e-8f90-abcdef123456",  # UUID
        "mrn-7731",  # medical record number
        "run-9f3a8e5b",  # run id
        "user-123",  # user id
    ],
)
def test_unsafe_or_identifier_like_label_values_rejected(value: str) -> None:
    with pytest.raises(TelemetryPolicyError):
        validate_metric_label("service", value)


def test_oversized_label_value_rejected() -> None:
    with pytest.raises(TelemetryPolicyError):
        validate_metric_label("service", "a" * 65)


def test_non_string_label_value_rejected() -> None:
    for bad in (42, 1.5, None, ["claimguard"]):
        with pytest.raises(TelemetryPolicyError):
            validate_metric_label("service", bad)  # type: ignore[arg-type]


def test_method_must_be_a_known_http_method() -> None:
    assert validate_metric_label("method", "GET") == "GET"
    for bad in ("FIND", "get", "GET /v1/claims", 200):
        with pytest.raises(TelemetryPolicyError):
            validate_metric_label("method", bad)  # type: ignore[arg-type]


def test_status_class_must_be_a_class_not_a_code() -> None:
    assert validate_metric_label("status_class", "4xx") == "4xx"
    for bad in ("200", "success", "404", "xx4"):
        with pytest.raises(TelemetryPolicyError):
            validate_metric_label("status_class", bad)


@pytest.mark.parametrize(
    "template",
    [
        "/v1/claims/CLM-0042",  # uppercase concrete id
        "/v1/claims/9f3a8e5b1b2c4d3e8f90abcdef123456",  # 32-hex segment
        "/v1/claims/9f3a8e5b-1b2c-4d3e-8f90-abcdef123456",  # UUID segment
        "/v1/claims/42",  # numeric concrete segment
        "/claims/{ClaimId}",  # uppercase placeholder
        "v1/claims/{claim_id}",  # not absolute
    ],
)
def test_route_template_rejects_concrete_identifiers(template: str) -> None:
    with pytest.raises(TelemetryPolicyError):
        validate_metric_label("route_template", template)


# ---------------------------------------------------------------------------
# Structured telemetry fields — allowed and rejected
# ---------------------------------------------------------------------------


def test_valid_telemetry_record_round_trip() -> None:
    assert validate_telemetry_fields(VALID_RECORD) == VALID_RECORD


def test_opaque_ids_accepted_when_uuid_or_32_lowercase_hex() -> None:
    record = {
        "correlation_id": str(uuid.uuid4()),
        "request_id": "9f3a8e5b1b2c4d3e8f90abcdef123456",
    }
    validated = validate_telemetry_fields(record)
    assert validated["correlation_id"] == str(uuid.UUID(record["correlation_id"]))
    assert validated["request_id"] == "9f3a8e5b1b2c4d3e8f90abcdef123456"


@pytest.mark.parametrize(
    "value",
    [
        "9F3A8E5B1B2C4D3E8F90ABCDEF123456",  # uppercase 32-hex — NOT retained
        "9f3a8e5b-1b2c-4d3e-8f90-abcdef12345",  # truncated UUID
        "CLM-0042",
        "abc",
        "not-an-id",
        "",
    ],
)
def test_unsafe_opaque_ids_rejected(value: str) -> None:
    with pytest.raises(TelemetryPolicyError):
        validate_telemetry_field("correlation_id", value)


def test_unknown_telemetry_field_rejected() -> None:
    with pytest.raises(TelemetryPolicyError):
        validate_telemetry_field("foo", "bar")
    with pytest.raises(TelemetryPolicyError):
        validate_telemetry_fields({"service": "claimguard", "foo": "bar"})


@pytest.mark.parametrize(
    "key",
    [
        "message",
        "exception",
        "error_message",
        "body",
        "request_body",
        "response_body",
        "header",
        "headers",
        "cookie",
        "cookies",
        "query",
        "query_string",
        "url",
        "sql",
        "prompt",
        "clinical",
        "diagnosis",
        "narrative",
        "patient_name",
        "note",
    ],
)
def test_free_text_and_payload_keys_rejected(key: str) -> None:
    with pytest.raises(TelemetryPolicyError):
        validate_telemetry_field(key, "anything")


def test_forbidden_identifier_keys_rejected_in_records() -> None:
    with pytest.raises(TelemetryPolicyError):
        validate_telemetry_field("claim_id", "CLM-0042")
    with pytest.raises(TelemetryPolicyError):
        validate_telemetry_field("email", "sara@example.com")


def test_duration_ms_validates_type_and_range() -> None:
    assert validate_telemetry_field("duration_ms", 0) == 0
    assert validate_telemetry_field("duration_ms", 3_600_000) == 3_600_000
    assert validate_telemetry_field("duration_ms", 150.5) == 150.5
    for bad in (-1, 3_600_001, float("nan"), float("inf"), "fast", True):
        with pytest.raises(TelemetryPolicyError):
            validate_telemetry_field("duration_ms", bad)  # type: ignore[arg-type]


def test_timestamp_validates_type_and_range() -> None:
    assert validate_telemetry_field("timestamp", "2026-09-28T10:00:00Z") == "2026-09-28T10:00:00Z"
    assert validate_telemetry_field("timestamp", 1_700_000_000) == 1_700_000_000
    for bad in (
        "yesterday",
        "2026-09-28T10:00:00.123456789012345678901234567890123",
        float("inf"),
        True,
    ):
        with pytest.raises(TelemetryPolicyError):
            validate_telemetry_field("timestamp", bad)  # type: ignore[arg-type]


def test_level_is_bounded() -> None:
    assert validate_telemetry_field("level", "warning") == "warning"
    with pytest.raises(TelemetryPolicyError):
        validate_telemetry_field("level", "URGENT")


# ---------------------------------------------------------------------------
# Validators never mutate their input
# ---------------------------------------------------------------------------


def test_validate_metric_labels_does_not_mutate_input() -> None:
    attrs = dict(VALID_LABELS)
    attrs["claim_id"] = "CLM-0042"
    before = dict(attrs)
    with pytest.raises(TelemetryPolicyError):
        validate_metric_labels(attrs)
    assert attrs == before


def test_validate_telemetry_fields_does_not_mutate_input() -> None:
    record = dict(VALID_RECORD)
    record["message"] = "boom"
    before = dict(record)
    with pytest.raises(TelemetryPolicyError):
        validate_telemetry_fields(record)
    assert record == before
