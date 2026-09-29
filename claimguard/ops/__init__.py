"""Operations package: telemetry safety policy and defensive sanitization.

P0 baseline / safety (docs/20 §13.6, docs/obs_trace.tex): telemetry is a
separate surface from the audit chain and must never carry PII/PHI, claim
content, or free text. This package defines the allow-list contract
(:mod:`claimguard.ops.telemetry_policy`) and the runtime-safe sanitizers that
enforce it (:mod:`claimguard.ops.redaction`).

The OpenTelemetry SDK wiring, exporters, and health/metrics adapters arrive in
P1 — nothing here initializes or depends on the SDK.
"""
