"""Telemetry safety policy: the allow-lists every emitter must obey.

P0 baseline / safety (docs/20 §13.6, docs/obs_trace.tex §4): telemetry is a
separate surface from the audit chain and must never carry PII/PHI, claim
content, or free text. The allow-lists and validators here are the single
source of truth for what may be emitted until the OpenTelemetry SDK is wired
in (P1).

Emitters call :func:`validate_metric_labels` / :func:`validate_telemetry_fields`
at their boundary and fail loudly on a violation (a bug in our own labels is a
defect, not a runtime event). The runtime-safe sanitizers that never raise live
in :mod:`claimguard.ops.redaction`.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable, Mapping
from typing import Final

# ---------------------------------------------------------------------------
# Allow-lists (docs/20 §13.6) — immutable by construction (frozenset).
# ---------------------------------------------------------------------------

#: Low-cardinality metric-label dimensions only. Identifiers (claim_id,
#: tenant_id, ...), correlation/request ids, and concrete routes are FORBIDDEN
#: as labels. Adding a label here requires a policy change, never a code hack.
METRIC_LABEL_ALLOWLIST: Final[frozenset[str]] = frozenset(
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

#: Superset of the label allow-list: correlation/request ids may appear in logs
#: and traces but NEVER as metric labels (docs/20 §13.6).
TELEMETRY_FIELD_ALLOWLIST: Final[frozenset[str]] = frozenset(
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

#: Identifier keys that are structurally forbidden in telemetry, named so a
#: reject is explicit ("forbidden identifier key") rather than a generic
#: unknown-key error.
FORBIDDEN_IDENTIFIER_KEYS: Final[frozenset[str]] = frozenset(
    {
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
    }
)

#: Free-text / payload keys forbidden in telemetry records. The allow-list gate
#: already drops them; this list exists to reject with a clear message and to
#: stay protective if the allow-list is ever widened.
FORBIDDEN_FREETEXT_KEYS: Final[frozenset[str]] = frozenset(
    {
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
        "query_params",
        "url",
        "sql",
        "prompt",
        "clinical",
        "diagnosis",
        "narrative",
        "patient_name",
        "note",
    }
)

MAX_SLUG_LENGTH: Final[int] = 64
MAX_ROUTE_TEMPLATE_LENGTH: Final[int] = 128
MAX_TIMESTAMP_LENGTH: Final[int] = 32
MAX_DURATION_MS: Final[float] = 3_600_000.0  # one hour
MAX_EPOCH_SECONDS: Final[float] = 4_102_444_800.0  # 2100-01-01T00:00:00Z

_ALLOWED_METHODS: Final[frozenset[str]] = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
)
_ALLOWED_STATUS_CLASSES: Final[frozenset[str]] = frozenset({"1xx", "2xx", "3xx", "4xx", "5xx"})
_ALLOWED_LEVELS: Final[frozenset[str]] = frozenset(
    {"debug", "info", "warning", "error", "critical"}
)

_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_HEX32_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{32}$")
_UUID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
#: Slug-shaped values that still smell like a concrete identifier: a word
#: followed by a hex-ish token (mrn-7731, user-123, run-9f3a8e5b).
_IDENTIFIER_LIKE_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z]+(?:[-_][0-9a-f]{3,})+$")
_ISO_CHARS_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9TZ:+\-.]{1,32}$")
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"^\{[a-z][a-z0-9_]*\}$")
_PATH_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.-]*$")


class TelemetryPolicyError(ValueError):
    """A telemetry attribute violates the P0 safety policy."""


# ---------------------------------------------------------------------------
# Value validators — each raises TelemetryPolicyError with the field name.
# ---------------------------------------------------------------------------


def _is_identifier_like(value: str) -> bool:
    """True when a slug-shaped value still looks like a concrete identifier."""
    return (
        _HEX32_RE.fullmatch(value) is not None
        or _UUID_RE.fullmatch(value) is not None
        or _IDENTIFIER_LIKE_RE.fullmatch(value) is not None
    )


def _validate_slug(field: str, value: object) -> str:
    """Validate a low-cardinality slug value (identifiers and free text excluded)."""
    if not isinstance(value, str):
        msg = f"{field}: expected a string, got {type(value).__name__}"
        raise TelemetryPolicyError(msg)
    if not 1 <= len(value) <= MAX_SLUG_LENGTH:
        msg = f"{field}: length {len(value)} outside 1..{MAX_SLUG_LENGTH}"
        raise TelemetryPolicyError(msg)
    if _SLUG_RE.fullmatch(value) is None:
        msg = (
            f"{field}: value {value!r} is not a safe slug "
            "(lowercase letters, digits, '_', '.', '-')"
        )
        raise TelemetryPolicyError(msg)
    if _is_identifier_like(value):
        msg = f"{field}: identifier-like value {value!r} is not allowed"
        raise TelemetryPolicyError(msg)
    return value


def _validate_route_template(field: str, value: object) -> str:
    """Validate a route TEMPLATE: placeholders allowed, concrete identifiers rejected."""
    if not isinstance(value, str):
        msg = f"{field}: expected a string, got {type(value).__name__}"
        raise TelemetryPolicyError(msg)
    if not 1 <= len(value) <= MAX_ROUTE_TEMPLATE_LENGTH:
        msg = f"{field}: length {len(value)} outside 1..{MAX_ROUTE_TEMPLATE_LENGTH}"
        raise TelemetryPolicyError(msg)
    if not value.startswith("/"):
        msg = f"{field}: must start with '/'"
        raise TelemetryPolicyError(msg)
    if any(ch.isupper() for ch in value):
        msg = f"{field}: uppercase characters indicate a concrete route identifier ({value!r})"
        raise TelemetryPolicyError(msg)
    if any(ch.isspace() or ch == "@" for ch in value):
        msg = f"{field}: value {value!r} contains whitespace or '@'"
        raise TelemetryPolicyError(msg)
    for segment in value.split("/")[1:]:
        if not segment:
            continue
        if _PLACEHOLDER_RE.fullmatch(segment) is not None:
            continue
        if _PATH_SEGMENT_RE.fullmatch(segment) is None:
            msg = f"{field}: unsafe route segment {segment!r}"
            raise TelemetryPolicyError(msg)
        if _HEX32_RE.fullmatch(segment) is not None or _UUID_RE.fullmatch(segment) is not None:
            msg = f"{field}: concrete identifier segment {segment!r}"
            raise TelemetryPolicyError(msg)
    return value


def _validate_method(field: str, value: object) -> str:
    """Validate an HTTP method against the bounded set."""
    if not isinstance(value, str) or value not in _ALLOWED_METHODS:
        msg = f"{field}: must be one of {sorted(_ALLOWED_METHODS)}"
        raise TelemetryPolicyError(msg)
    return value


def _validate_status_class(field: str, value: object) -> str:
    """Validate an HTTP status CLASS (2xx), never a concrete status code."""
    if not isinstance(value, str) or value not in _ALLOWED_STATUS_CLASSES:
        msg = f"{field}: must be one of {sorted(_ALLOWED_STATUS_CLASSES)}"
        raise TelemetryPolicyError(msg)
    return value


def _validate_level(field: str, value: object) -> str:
    """Validate a structured log level against the bounded set."""
    if not isinstance(value, str) or value not in _ALLOWED_LEVELS:
        msg = f"{field}: must be one of {sorted(_ALLOWED_LEVELS)}"
        raise TelemetryPolicyError(msg)
    return value


def _validate_duration_ms(field: str, value: object) -> int | float:
    """Validate a finite duration in milliseconds within a sane range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"{field}: expected a number, got {type(value).__name__}"
        raise TelemetryPolicyError(msg)
    if not math.isfinite(float(value)):
        msg = f"{field}: must be finite"
        raise TelemetryPolicyError(msg)
    if value < 0 or value > MAX_DURATION_MS:
        msg = f"{field}: {value!r} outside 0..{MAX_DURATION_MS:g}"
        raise TelemetryPolicyError(msg)
    return value


def _validate_timestamp(field: str, value: object) -> str | int | float:
    """Validate a timestamp: ISO-8601-like string or a finite epoch within range."""
    if isinstance(value, bool):
        msg = f"{field}: bool is not a timestamp"
        raise TelemetryPolicyError(msg)
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or not 0 <= value <= MAX_EPOCH_SECONDS:
            msg = f"{field}: numeric timestamp outside 0..{MAX_EPOCH_SECONDS:g}"
            raise TelemetryPolicyError(msg)
        return value
    if isinstance(value, str):
        if not 1 <= len(value) <= MAX_TIMESTAMP_LENGTH or _ISO_CHARS_RE.fullmatch(value) is None:
            msg = f"{field}: value {value!r} is not an ISO-8601-like timestamp"
            raise TelemetryPolicyError(msg)
        return value
    msg = f"{field}: expected str/int/float, got {type(value).__name__}"
    raise TelemetryPolicyError(msg)


def _validate_opaque_id(field: str, value: object) -> str:
    """Validate an opaque correlation/request id.

    Retained only when it is a canonical lowercase UUID or exactly 32 lowercase
    hex characters. An uppercase 32-hex string is NOT a valid opaque id here —
    it is dropped rather than normalized (docs/20 §13.6 keeps correlation ids
    opaque; we do not guess at case).
    """
    if not isinstance(value, str) or not value:
        msg = f"{field}: expected a non-empty string"
        raise TelemetryPolicyError(msg)
    if len(value) > 36:
        msg = f"{field}: length {len(value)} exceeds the UUID format length"
        raise TelemetryPolicyError(msg)
    if _HEX32_RE.fullmatch(value) is not None:
        return value
    if len(value) == 36 and value.count("-") == 4:
        try:
            parsed = uuid.UUID(value)
        except ValueError:
            msg = f"{field}: {value!r} is not a valid UUID"
            raise TelemetryPolicyError(msg) from None
        return str(parsed)
    msg = f"{field}: {value!r} is not a UUID or 32 lowercase hex characters"
    raise TelemetryPolicyError(msg)


# ---------------------------------------------------------------------------
# Per-field rules. A value passes only its field's rule.
# ---------------------------------------------------------------------------

_LABEL_RULES: Final[dict[str, Callable[[str, object], str]]] = {
    "service": _validate_slug,
    "component": _validate_slug,
    "route_template": _validate_route_template,
    "method": _validate_method,
    "status_class": _validate_status_class,
    "queue_job_category": _validate_slug,
    "integration_category": _validate_slug,
}

_RECORD_RULES: Final[dict[str, Callable[[str, object], object]]] = {
    "timestamp": _validate_timestamp,
    "level": _validate_level,
    "service": _validate_slug,
    "component": _validate_slug,
    "route_template": _validate_route_template,
    "method": _validate_method,
    "status_class": _validate_status_class,
    "duration_ms": _validate_duration_ms,
    "error_category": _validate_slug,
    "queue_job_category": _validate_slug,
    "integration_category": _validate_slug,
    "correlation_id": _validate_opaque_id,
    "request_id": _validate_opaque_id,
    "version": _validate_slug,
}


# ---------------------------------------------------------------------------
# Public policy surface — strict, raises on the first violation.
# ---------------------------------------------------------------------------


def validate_metric_label(key: str, value: object) -> str:
    """Validate one metric label against the P0 allow-list (raises on violation)."""
    if key in FORBIDDEN_IDENTIFIER_KEYS:
        msg = f"metric label {key!r} is a forbidden identifier key"
        raise TelemetryPolicyError(msg)
    if key not in METRIC_LABEL_ALLOWLIST:
        if key in TELEMETRY_FIELD_ALLOWLIST:
            msg = (
                f"metric label {key!r} is not label-allow-listed; correlation_id/request_id "
                "may appear in logs/traces but never as metric labels"
            )
            raise TelemetryPolicyError(msg)
        msg = f"unknown metric label {key!r}"
        raise TelemetryPolicyError(msg)
    return _LABEL_RULES[key](key, value)


def validate_metric_labels(attrs: Mapping[str, object]) -> dict[str, str]:
    """Validate a metric-label set; returns a validated copy, raises on the first violation."""
    validated: dict[str, str] = {}
    for key, value in attrs.items():
        validated[key] = validate_metric_label(key, value)
    return validated


def validate_telemetry_field(key: str, value: object) -> object:
    """Validate one structured telemetry field (raises on violation)."""
    if key in FORBIDDEN_IDENTIFIER_KEYS:
        msg = f"telemetry field {key!r} is a forbidden identifier key"
        raise TelemetryPolicyError(msg)
    if key in FORBIDDEN_FREETEXT_KEYS:
        msg = f"telemetry field {key!r} is a forbidden free-text key"
        raise TelemetryPolicyError(msg)
    if key not in TELEMETRY_FIELD_ALLOWLIST:
        msg = f"unknown telemetry field {key!r}"
        raise TelemetryPolicyError(msg)
    return _RECORD_RULES[key](key, value)


def validate_telemetry_fields(record: Mapping[str, object]) -> dict[str, object]:
    """Validate a structured telemetry record; returns a copy, raises on first violation."""
    validated: dict[str, object] = {}
    for key, value in record.items():
        validated[key] = validate_telemetry_field(key, value)
    return validated
