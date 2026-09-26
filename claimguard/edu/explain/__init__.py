"""Bounded AI explanation layer for the ClaimGuard rule engine.

Package layout:

*   :mod:`claimguard.edu.explain.fallback` — the deterministic text path and its
    provenance marker (always available, no model, no network);
*   :mod:`claimguard.edu.explain.verifier` — the pack's ``validate_explanation``
    contract plus the guards the pack itself asks for (no adjudication or
    clinical assertions, citations must resolve in the original envelope, no
    empty or rule-echoing text);
*   :mod:`claimguard.edu.explain.provider` — the ``ExplanationProvider`` seam,
    the deterministic and OpenAI-compatible model providers, and record
    enrichment that can change exactly one field: ``explanation``.

Required MVP behaviour 6 ("a model failure cannot remove a deterministic
finding") is enforced structurally: :func:`explain_finding` copies
``status``/``severity``/``evidence``/``requires_human_review`` from the finding
and never recomputes them, and every provider fault — absence, timeout,
malformed payload, rejected output — returns the deterministic text with the
reasons recorded on the outcome.
"""

from __future__ import annotations

from claimguard.edu.explain.fallback import (
    DETERMINISTIC_PREFIX,
    MODEL_PREFIX,
    SOURCE_DETERMINISTIC,
    SOURCE_MODEL,
    FallbackError,
    build_explanation,
    build_text,
    evidence_pairs,
    evidence_paths,
    mark_deterministic,
    mark_model,
    render_value,
)
from claimguard.edu.explain.provider import (
    ASSISTANCE_PROMPT_VERSION,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT,
    ENV_API_KEY,
    ENV_BASE_URL,
    ENV_MAX_TOKENS,
    ENV_MODEL,
    ENV_TIMEOUT,
    MAX_UNTRUSTED_CHARS,
    MODEL_ELIGIBLE_STATUSES,
    PROMPT_SHA256,
    PROMPT_SOURCE,
    PROMPT_VERSION,
    RULE_EXCERPT_CHARS,
    SECURE_ASSISTANCE_PROMPT,
    SECURITY_DECISION_ACCEPT,
    SECURITY_DECISION_DECLINE,
    SECURITY_DECISION_FALLBACK,
    SYSTEM_PROMPT,
    ExplanationOutcome,
    ExplanationProvider,
    JsonTransport,
    ModelExplanationProvider,
    ModelSettings,
    ProviderError,
    RuleSource,
    TemplateExplanationProvider,
    UnavailableModelProvider,
    apply_outcome,
    apply_outcomes,
    assistance_receipt,
    default_transport,
    enrich_records,
    explain_finding,
    explain_records,
    has_citable_evidence,
    provider_name,
    provider_source_kind,
    resolve_rule,
    untrusted_text_for,
)
from claimguard.edu.explain.verifier import (
    EXPLANATION_KEYS,
    PROHIBITED_PATTERNS,
    ExplanationRejectionError,
    prohibited_assertions,
    validate_explanation,
)

__all__ = [
    "ASSISTANCE_PROMPT_VERSION",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TIMEOUT",
    "DETERMINISTIC_PREFIX",
    "ENV_API_KEY",
    "ENV_BASE_URL",
    "ENV_MAX_TOKENS",
    "ENV_MODEL",
    "ENV_TIMEOUT",
    "EXPLANATION_KEYS",
    "MAX_UNTRUSTED_CHARS",
    "MODEL_ELIGIBLE_STATUSES",
    "MODEL_PREFIX",
    "PROHIBITED_PATTERNS",
    "PROMPT_SHA256",
    "PROMPT_SOURCE",
    "PROMPT_VERSION",
    "RULE_EXCERPT_CHARS",
    "SECURE_ASSISTANCE_PROMPT",
    "SECURITY_DECISION_ACCEPT",
    "SECURITY_DECISION_DECLINE",
    "SECURITY_DECISION_FALLBACK",
    "SOURCE_DETERMINISTIC",
    "SOURCE_MODEL",
    "SYSTEM_PROMPT",
    "ExplanationOutcome",
    "ExplanationProvider",
    "ExplanationRejectionError",
    "FallbackError",
    "JsonTransport",
    "ModelExplanationProvider",
    "ModelSettings",
    "ProviderError",
    "RuleSource",
    "TemplateExplanationProvider",
    "UnavailableModelProvider",
    "apply_outcome",
    "apply_outcomes",
    "assistance_receipt",
    "build_explanation",
    "build_text",
    "default_transport",
    "enrich_records",
    "evidence_pairs",
    "evidence_paths",
    "explain_finding",
    "explain_records",
    "has_citable_evidence",
    "mark_deterministic",
    "mark_model",
    "prohibited_assertions",
    "provider_name",
    "provider_source_kind",
    "render_value",
    "resolve_rule",
    "untrusted_text_for",
    "validate_explanation",
]
