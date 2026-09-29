"""Defensive telemetry sanitization.

:mod:`claimguard.ops.telemetry_policy` is the contract; this module is the
runtime-safe edge enforcement. Sanitizers NEVER raise — telemetry is fail-open
(docs/obs_trace.tex §5, docs/20 §13.6): a malformed attribute or a collector
outage must never break the claim flow.

Each sanitizer copies the input, keeps only allow-listed fields whose values
validate, and omits everything else — including free-text/identifier keys and
correlation/request ids that are not a valid UUID or exactly 32 lowercase hex.
The input mapping is never mutated.
"""

from __future__ import annotations

from collections.abc import Mapping

from claimguard.ops.telemetry_policy import (
    METRIC_LABEL_ALLOWLIST,
    TELEMETRY_FIELD_ALLOWLIST,
    TelemetryPolicyError,
    validate_metric_label,
    validate_telemetry_field,
)


def sanitize_metric_labels(attrs: Mapping[str, object]) -> dict[str, str]:
    """Return a safe copy of ``attrs`` with only valid allow-listed labels.

    Any key outside the metric-label allow-list and any value that violates the
    policy is omitted. Never raises.
    """
    safe: dict[str, str] = {}
    for key, value in attrs.items():
        if key not in METRIC_LABEL_ALLOWLIST:
            continue
        try:
            safe[key] = validate_metric_label(key, value)
        except TelemetryPolicyError:
            continue
    return safe


def sanitize_telemetry_record(record: Mapping[str, object]) -> dict[str, object]:
    """Return a safe copy of ``record`` with only validated allow-listed fields.

    Forbidden free-text/identifier keys are dropped by the allow-list gate;
    ``correlation_id``/``request_id`` survive only when they are a valid UUID or
    exactly 32 lowercase hex characters, and are omitted otherwise. Never raises.
    """
    safe: dict[str, object] = {}
    for key, value in record.items():
        if key not in TELEMETRY_FIELD_ALLOWLIST:
            continue
        try:
            safe[key] = validate_telemetry_field(key, value)
        except TelemetryPolicyError:
            continue
    return safe
