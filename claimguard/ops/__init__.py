"""Operations package: telemetry safety policy and defensive sanitization.

P0 baseline / safety (docs/20 §13.6, docs/obs_trace.tex): telemetry is a
separate surface from the audit chain and must never carry PII/PHI, claim
content, or free text. This package defines the allow-list contract
(:mod:`claimguard.ops.telemetry_policy`) and the runtime-safe sanitizers that
enforce it (:mod:`claimguard.ops.redaction`).

:mod:`claimguard.ops.telemetry` adds the optional, off-by-default OpenTelemetry
wiring (P1): no provider is registered, no socket is opened and no middleware is
added unless ``CLAIMGUARD_OPS_OTEL_ENABLED`` is explicitly truthy. Health, log,
trace and alert adapters arrive in P2.
"""
