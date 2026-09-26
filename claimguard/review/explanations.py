"""The reviewer layer's use of the bounded explanation layer (pack behaviour 6).

WHAT THIS MODULE IS
-------------------
The adapter between :mod:`claimguard.edu.explain` — which owns the language, the
pack's verification contract and the deterministic fallback — and the reviewer
workflow, which owns persistence and the HTTP surface. At run creation it:

1.  **chooses a provider.** The deterministic template by default; the
    OpenAI-compatible model provider only when ``CLAIMGUARD_EXPLAIN_MODE=model``
    and the endpoint/model variables are both configured. The default is an
    explicit deterministic selection; stale endpoint settings cannot activate a
    model, and a half-configured model mode degrades instead of failing.
2.  **explains the run through the layer's own orchestration**
    (:func:`claimguard.edu.explain.explain_records`), so the model-status gate
    (a PASS is never sent to a model), the citation checks, the prohibited-
    assertion guards and every fallback stay where they are implemented and
    tested — this module re-implements none of them.
3.  **re-validates the enriched records against the engine's own model**
    (:class:`claimguard.edu.envelope.ResultRecord`, ``extra="forbid"``). That is
    what keeps the frozen contract frozen: an enrichment that added, dropped or
    renamed a key fails here, in-process, instead of reaching the scorer. The
    only field the layer may change is ``explanation``; every other key is copied
    through and re-checked.
4.  **returns the records with their provenance**, which the store persists in
    the ``claimguard.run_explanations`` sidecar and the API serves *beside* the
    records — never inside them, because the 15-key record has no room for a
    sixteenth key.

WHAT IT CANNOT DO
-----------------
Change a status, a severity, an evidence pointer, a corrective action or the
human-review boundary. A provider that is absent, slow, malformed or rejected by
the verifier leaves the deterministic text in place with the reasons recorded on
the provenance; a failure never becomes an HTTP error and never becomes a
different status.

The claim's untrusted free text (``notes``, attachment ``text``) is **not**
forwarded: the caller has to opt in per run, and nothing here opts in. A model
sees the validated finding, its evidence pointers and a bounded rule excerpt.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

from claimguard.edu.envelope import ResultRecord
from claimguard.edu.explain import (
    ASSISTANCE_PROMPT_VERSION,
    MODEL_ELIGIBLE_STATUSES,
    SOURCE_DETERMINISTIC,
    SOURCE_MODEL,
    ExplanationOutcome,
    ExplanationProvider,
    FallbackError,
    ModelExplanationProvider,
    RuleSource,
    TemplateExplanationProvider,
    UnavailableModelProvider,
    apply_outcomes,
    assistance_receipt,
    explain_records,
    provider_name,
    provider_source_kind,
)
from claimguard.review.models import ExplanationProvenance

#: Model/prompt identity of the deterministic engine. The rule path uses no
#: prompt, and this records that fact instead of inventing a version for one that
#: does not exist.
ENGINE_MODEL_VERSION: Final = "deterministic-engine/1.0.0"
ENGINE_PROMPT_VERSION: Final = "none"

#: Prefix of the model identity a run records when the explanation layer used a
#: model. The wording is explicit on purpose: the model drafted *text*, and the
#: value must not read as if a model produced a status (pack behaviour 6).
MODEL_VERSION_PREFIX: Final = "explanation-model/"
EXPLANATION_MODE_ENV: Final = "CLAIMGUARD_EXPLAIN_MODE"


@dataclass(frozen=True)
class ExplainedRun:
    """A run's records with reviewer-facing text, plus how that text was produced.

    ``records`` are the same 15 records the engine produced, with
    ``explanation`` replaced by the layer's text where the layer rewrote it;
    ``provenance`` says, per record, which provider produced the text and whether
    a fallback stood in. ``model_version``/``prompt_version`` are the run-level
    identity of everything that produced that text.
    """

    records: list[ResultRecord]
    provenance: list[ExplanationProvenance]
    model_version: str
    prompt_version: str


def explanation_provider(env: Mapping[str, str] | None = None) -> ExplanationProvider:
    """The configured explanation provider: the model when configured, else the template.

    The model path is opt-in through ``CLAIMGUARD_EXPLAIN_MODE=model`` plus
    ``CLAIMGUARD_EXPLAIN_MODEL`` and ``CLAIMGUARD_EXPLAIN_BASE_URL``. Any other
    mode selects the deterministic template. This makes a benchmark rejection a
    durable deployment decision instead of relying on empty or forgotten values.
    """
    source = os.environ if env is None else env
    mode = (source.get(EXPLANATION_MODE_ENV) or "deterministic").strip().lower()
    if mode != "model":
        return TemplateExplanationProvider()
    model = ModelExplanationProvider.from_env(source)
    return UnavailableModelProvider() if model is None else model


def run_identity(provider: ExplanationProvider) -> tuple[str, str]:
    """The ``(model_version, prompt_version)`` a run records for ``provider``.

    A run whose reviewer-facing text may be drafted by a model records that model
    and the explanation prompt version: a run is bound to the versions of
    everything that produced it (pack behaviour 7), and the explanation text is
    part of what the reviewer reads. A run explained deterministically records the
    engine's own identity, exactly as before. The per-record provenance in the
    sidecar remains the precise answer to "which text was model-assisted".
    """
    if provider_source_kind(provider) != SOURCE_MODEL:
        return ENGINE_MODEL_VERSION, ENGINE_PROMPT_VERSION
    return f"{MODEL_VERSION_PREFIX}{_model_id(provider)}", ASSISTANCE_PROMPT_VERSION


def _model_id(provider: ExplanationProvider) -> str:
    """The model identifier a provider is configured with, or its declared name."""
    if isinstance(provider, ModelExplanationProvider):
        return provider.settings.model
    return provider_name(provider)


def explain_run(
    records: Sequence[ResultRecord],
    rules: RuleSource,
    envelope: Mapping[str, Any],
    *,
    provider: ExplanationProvider | None = None,
) -> ExplainedRun:
    """Explain a run's records, keeping the 15-key contract intact.

    ``provider=None`` resolves the configured provider (see
    :func:`explanation_provider`). ``envelope`` is the ORIGINAL submitted claim:
    it is what lets the layer check that every citation resolves against what the
    caller actually sent, so it must not be a re-coerced copy.
    """
    chosen = explanation_provider() if provider is None else provider
    model_version, prompt_version = run_identity(chosen)
    engine_records = [record.model_dump(mode="json") for record in records]
    try:
        outcomes = explain_records(engine_records, rules, chosen, envelope=envelope)
    except FallbackError as exc:
        # The layer refused to rewrite the run at all (a record it cannot
        # explain, or a rule missing from the manifest). That is not a reason to
        # fail a submission: the engine's own explanation is complete and
        # evidence-linked, so it stands, and the provenance says why.
        reason = f"the explanation layer declined this run: {exc}"
        return ExplainedRun(
            records=[ResultRecord.model_validate(record) for record in engine_records],
            provenance=[
                _engine_text_provenance(index, record, provider_name(chosen), reason)
                for index, record in enumerate(engine_records, start=1)
            ],
            model_version=model_version,
            prompt_version=prompt_version,
        )
    enriched = [
        ResultRecord.model_validate(record) for record in apply_outcomes(engine_records, outcomes)
    ]
    return ExplainedRun(
        records=enriched,
        provenance=[
            _provenance_from_outcome(index, outcome)
            for index, outcome in enumerate(outcomes, start=1)
        ],
        model_version=model_version,
        prompt_version=prompt_version,
    )


def _provenance_from_outcome(index: int, outcome: ExplanationOutcome) -> ExplanationProvenance:
    """The provenance the API serves and the store persists, from one outcome."""
    return ExplanationProvenance(
        rule_id=outcome.rule_id,
        seq=index,
        source=outcome.source,
        provider=outcome.provider,
        rewritten=outcome.rewritten,
        fallback_used=outcome.fallback_used,
        correction_recommendation=outcome.correction_recommendation,
        cited_evidence_paths=list(outcome.cited_evidence_paths),
        security_decision=outcome.security_decision,
        receipt_sha256=outcome.receipt_sha256,
        rejection_reasons=list(outcome.rejection_reasons),
        declined_reason=outcome.declined_reason,
    )


def _engine_text_provenance(
    index: int, record: Mapping[str, Any], provider: str, reason: str
) -> ExplanationProvenance:
    """Provenance for a record whose engine text stands unrewritten."""
    evidence = record.get("evidence")
    entries = cast("list[Any]", evidence) if isinstance(evidence, list) else []
    paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        path = cast("Mapping[str, Any]", entry).get("path")
        if isinstance(path, str):
            paths.append(path)
    outcome = ExplanationOutcome(
        claim_id=str(record.get("claim_id") or ""),
        rule_id=str(record.get("rule_id") or ""),
        status=str(record.get("status") or ""),
        explanation=str(record.get("explanation") or ""),
        correction_recommendation=str(
            record.get("corrective_action") or "Review the cited evidence."
        ),
        cited_evidence_paths=tuple(paths),
        cited_rule_ids=(str(record.get("rule_id") or ""),),
        needs_human_review=record.get("requires_human_review") is True,
        source=SOURCE_DETERMINISTIC,
        provider=provider,
        rewritten=False,
        fallback_used=True,
        security_decision="fallback",
        rejection_reasons=(reason,),
    )
    return ExplanationProvenance(
        rule_id=str(record.get("rule_id") or ""),
        seq=index,
        source=SOURCE_DETERMINISTIC,
        provider=provider,
        rewritten=False,
        fallback_used=True,
        correction_recommendation=outcome.correction_recommendation,
        cited_evidence_paths=paths,
        security_decision=outcome.security_decision,
        receipt_sha256=assistance_receipt(outcome),
        rejection_reasons=[reason],
    )


__all__ = [
    "ENGINE_MODEL_VERSION",
    "ENGINE_PROMPT_VERSION",
    "MODEL_ELIGIBLE_STATUSES",
    "MODEL_VERSION_PREFIX",
    "ExplainedRun",
    "explain_run",
    "explanation_provider",
    "run_identity",
]
