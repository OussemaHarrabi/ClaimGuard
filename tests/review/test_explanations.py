"""The reviewer layer's use of the bounded explanation layer (pack behaviour 6).

Pure unit tests: no database, no network, always run (CI included). The model
provider is exercised with an injected transport — a function, not an HTTP
client — so "a model is configured" is tested without a model, a key or a socket.

WHAT IS PINNED HERE
-------------------
*   With nothing configured, the provider is the deterministic template: the
    default deployment behaves as it did before the layer was wired in, apart from
    the wording of the explanation.
*   With a model configured, the model drafts the text and the deterministic path
    stands behind every failure — and a failure never reaches a status.
*   The enriched record keeps the frozen 15-key contract: only ``explanation``
    may differ from the engine's own output, and the provenance says who wrote it.
*   A PASS is never sent to a model, and the claim's untrusted free text is never
    forwarded to one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from claimguard.edu.engine import evaluate_claim
from claimguard.edu.envelope import RESULT_KEYS, ResultRecord, Status
from claimguard.edu.explain import (
    ASSISTANCE_PROMPT_VERSION,
    DETERMINISTIC_PREFIX,
    MODEL_PREFIX,
    SOURCE_DETERMINISTIC,
    SOURCE_MODEL,
    ModelExplanationProvider,
    TemplateExplanationProvider,
    UnavailableModelProvider,
)
from claimguard.review.explanations import (
    ENGINE_MODEL_VERSION,
    ENGINE_PROMPT_VERSION,
    MODEL_VERSION_PREFIX,
    explain_run,
    explanation_provider,
    run_identity,
)
from claimguard.review.models import EXPLANATION_SOURCES

from tests.edu import base_claim, rules_context
from tests.review.conftest import TEST_MODEL_NAME, ScriptedModelTransport, model_provider
from tests.review_ui.conftest import HARNESS, requires_node, run_node

pytestmark = pytest.mark.unit

MODEL_NAME = TEST_MODEL_NAME


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def coverage_lapse() -> dict[str, Any]:
    """A claim whose R003 fails: coverage ends before the service date."""
    envelope = base_claim()
    envelope["claim_id"] = "CG-EXPLAIN-LAPSE"
    envelope["coverage"]["end_date"] = "2026-03-09"
    return envelope


def engine_records(envelope: Mapping[str, Any]) -> list[ResultRecord]:
    """The engine's own records for ``envelope``, in R001..R015 order."""
    return [
        ResultRecord.model_validate(record) for record in evaluate_claim(envelope, rules_context())
    ]


def other_keys(record: Mapping[str, Any]) -> dict[str, Any]:
    """Every key of a result record except ``explanation``."""
    return {key: value for key, value in record.items() if key != "explanation"}


def jsonable(record: ResultRecord) -> dict[str, Any]:
    """A record as plain JSON data, the way it travels over the wire."""
    return record.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Provider choice and run identity
# ---------------------------------------------------------------------------


def test_no_configured_model_uses_the_deterministic_provider() -> None:
    """The default deployment explains without a model — and needs no configuration."""
    assert isinstance(explanation_provider({}), TemplateExplanationProvider)
    assert isinstance(
        explanation_provider({"CLAIMGUARD_EXPLAIN_MODEL": MODEL_NAME}),
        TemplateExplanationProvider,
    ), "a half-configured model path must degrade, not raise"


def test_stale_model_settings_do_not_override_the_deterministic_selection() -> None:
    provider = explanation_provider(
        {
            "CLAIMGUARD_EXPLAIN_MODEL": MODEL_NAME,
            "CLAIMGUARD_EXPLAIN_BASE_URL": "http://model.test/v1",
        }
    )
    assert isinstance(provider, TemplateExplanationProvider)


def test_an_explicit_model_mode_uses_a_fully_configured_model() -> None:
    provider = explanation_provider(
        {
            "CLAIMGUARD_EXPLAIN_MODE": "model",
            "CLAIMGUARD_EXPLAIN_MODEL": MODEL_NAME,
            "CLAIMGUARD_EXPLAIN_BASE_URL": "http://model.test/v1",
        }
    )
    assert isinstance(provider, ModelExplanationProvider)
    assert provider.settings.model == MODEL_NAME


def test_explicit_model_mode_without_an_endpoint_is_a_visible_fallback() -> None:
    provider = explanation_provider({"CLAIMGUARD_EXPLAIN_MODE": "model"})
    assert isinstance(provider, UnavailableModelProvider)

    envelope = coverage_lapse()
    explained = explain_run(engine_records(envelope), rules_context(), envelope, provider=provider)
    failing = next(entry for entry in explained.provenance if entry.rule_id == "R003")
    assert failing.fallback_used is True
    assert failing.security_decision == "fallback"
    assert "not fully configured" in " ".join(failing.rejection_reasons)


def test_run_identity_records_what_produced_the_wording() -> None:
    """A deterministic run keeps the engine's identity; a model run names the model."""
    assert run_identity(TemplateExplanationProvider()) == (
        ENGINE_MODEL_VERSION,
        ENGINE_PROMPT_VERSION,
    )
    assert run_identity(model_provider(ScriptedModelTransport())) == (
        f"{MODEL_VERSION_PREFIX}{MODEL_NAME}",
        ASSISTANCE_PROMPT_VERSION,
    )


# ---------------------------------------------------------------------------
# Deterministic enrichment
# ---------------------------------------------------------------------------


def test_the_deterministic_path_replaces_only_the_explanation() -> None:
    """Every other key of the frozen contract is byte-identical to the engine's."""
    envelope = coverage_lapse()
    records = engine_records(envelope)

    explained = explain_run(
        records, rules_context(), envelope, provider=TemplateExplanationProvider()
    )

    assert len(explained.records) == 15
    assert [record.rule_id for record in explained.records] == [
        f"R{index:03d}" for index in range(1, 16)
    ]
    for enriched, original in zip(explained.records, records, strict=True):
        assert set(jsonable(enriched)) == set(RESULT_KEYS), "the record's key set changed"
        assert other_keys(jsonable(enriched)) == other_keys(jsonable(original))
    assert all(record.explanation.startswith(DETERMINISTIC_PREFIX) for record in explained.records)
    assert explained.model_version == ENGINE_MODEL_VERSION
    assert explained.prompt_version == ENGINE_PROMPT_VERSION


def test_provenance_covers_every_record_once_and_in_order() -> None:
    envelope = coverage_lapse()
    explained = explain_run(
        engine_records(envelope), rules_context(), envelope, provider=TemplateExplanationProvider()
    )

    assert [entry.seq for entry in explained.provenance] == list(range(1, 16))
    assert [entry.rule_id for entry in explained.provenance] == [
        record.rule_id for record in explained.records
    ]
    assert all(entry.source in EXPLANATION_SOURCES for entry in explained.provenance)
    assert all(entry.provider == "template" for entry in explained.provenance)
    assert all(entry.rewritten for entry in explained.provenance)
    assert not any(entry.fallback_used for entry in explained.provenance)
    assert not any(entry.model_assisted for entry in explained.provenance)


# ---------------------------------------------------------------------------
# The model path
# ---------------------------------------------------------------------------


def test_a_model_drafts_the_text_and_is_marked_as_the_source() -> None:
    envelope = coverage_lapse()
    transport = ScriptedModelTransport()
    explained = explain_run(
        engine_records(envelope), rules_context(), envelope, provider=model_provider(transport)
    )

    failing = next(entry for entry in explained.provenance if entry.rule_id == "R003")
    assert failing.source == SOURCE_MODEL
    assert failing.model_assisted is True
    assert failing.provider == "model"
    assert failing.fallback_used is False
    assert failing.correction_recommendation.startswith(MODEL_PREFIX)
    assert failing.security_decision == "accept"
    assert failing.receipt_sha256 is not None
    assert len(failing.receipt_sha256) == 64
    assert failing.cited_evidence_paths
    record = next(record for record in explained.records if record.rule_id == "R003")
    assert record.explanation.startswith(MODEL_PREFIX)
    assert "A model drafted this sentence for R003" in record.explanation
    assert explained.model_version == f"{MODEL_VERSION_PREFIX}{MODEL_NAME}"
    assert explained.prompt_version == ASSISTANCE_PROMPT_VERSION


def test_a_model_never_changes_a_status() -> None:
    """Required behaviour 6: the model writes language, the engine owns the outcome."""
    envelope = coverage_lapse()
    records = engine_records(envelope)
    explained = explain_run(
        records, rules_context(), envelope, provider=model_provider(ScriptedModelTransport())
    )

    for enriched, original in zip(explained.records, records, strict=True):
        assert other_keys(jsonable(enriched)) == other_keys(jsonable(original))
    assert next(r for r in explained.records if r.rule_id == "R003").status is Status.FAIL


def test_a_model_failure_keeps_the_deterministic_text_and_records_why() -> None:
    envelope = coverage_lapse()
    records = engine_records(envelope)
    explained = explain_run(
        records,
        rules_context(),
        envelope,
        provider=model_provider(ScriptedModelTransport(fail=True)),
    )

    failing = next(entry for entry in explained.provenance if entry.rule_id == "R003")
    assert failing.source == SOURCE_DETERMINISTIC
    assert failing.fallback_used is True
    assert failing.model_assisted is False
    assert failing.rejection_reasons, "a fallback must say why it happened"
    assert "endpoint refused the connection" in failing.rejection_reasons[0]
    record = next(record for record in explained.records if record.rule_id == "R003")
    assert record.explanation.startswith(DETERMINISTIC_PREFIX)
    assert other_keys(jsonable(record)) == other_keys(jsonable(records[2]))


def test_only_attention_findings_are_sent_to_a_model() -> None:
    """A PASS is never sent to a model: it cannot improve it, and it invites a
    "passed check → payer acceptance" reading (the layer's own gate)."""
    envelope = coverage_lapse()
    transport = ScriptedModelTransport()
    explained = explain_run(
        engine_records(envelope), rules_context(), envelope, provider=model_provider(transport)
    )

    eligible = [
        record.rule_id
        for record in explained.records
        if record.status in (Status.FAIL, Status.UNABLE_TO_ASSESS, Status.NOT_IMPLEMENTED)
    ]
    assert len(transport.calls) == len(eligible)
    for entry in explained.provenance:
        if entry.rule_id in eligible:
            continue
        assert entry.source == SOURCE_DETERMINISTIC
        assert entry.declined_reason, "a record not sent to a model says so"
        assert entry.model_assisted is False


def test_the_claims_untrusted_text_is_never_forwarded_to_a_model() -> None:
    """Claim notes and attachment text are data; nothing here opts them in."""
    envelope = coverage_lapse()
    envelope["notes"] = "SYNTHETIC-NOTE-THAT-MUST-NOT-BE-SENT"
    transport = ScriptedModelTransport()
    explain_run(
        engine_records(envelope), rules_context(), envelope, provider=model_provider(transport)
    )

    assert transport.calls, "the model path did run"
    for payload in transport.calls:
        body = json.dumps(payload)
        assert "SYNTHETIC-NOTE-THAT-MUST-NOT-BE-SENT" not in body
        assert "untrusted_data" not in body


# ---------------------------------------------------------------------------
# The layer refusing a run
# ---------------------------------------------------------------------------


def test_a_run_the_layer_cannot_rewrite_keeps_the_engine_text() -> None:
    """A rule missing from the manifest must not fail a submission.

    ``explain_records`` raises when it cannot resolve a record's rule: the run is
    then explained by the engine's own wording, and the provenance says so rather
    than leaving the reviewer with an unmarked explanation.
    """
    envelope = coverage_lapse()
    records = engine_records(envelope)

    explained = explain_run(records, {}, envelope, provider=TemplateExplanationProvider())

    assert [record.explanation for record in explained.records] == [
        record.explanation for record in records
    ]
    assert all(entry.rewritten is False for entry in explained.provenance)
    assert all(entry.fallback_used is True for entry in explained.provenance)
    assert all(entry.rejection_reasons for entry in explained.provenance)
    assert all(entry.source == SOURCE_DETERMINISTIC for entry in explained.provenance)
    for enriched, original in zip(explained.records, records, strict=True):
        assert other_keys(jsonable(enriched)) == other_keys(jsonable(original))


# ---------------------------------------------------------------------------
# The marker the reviewer reads
# ---------------------------------------------------------------------------

#: A payload that would execute if the interface ever wrote a value as markup.
#: Rejection reasons quote a model's output verbatim, so they are untrusted too.
SCRIPT_PAYLOAD = "<script>alert('model-output')</script>"


def finding_payload(provenance: Mapping[str, Any] | None) -> dict[str, Any]:
    """A payload for the shipped renderer: one record, with or without provenance."""
    record = jsonable(
        next(record for record in engine_records(coverage_lapse()) if record.rule_id == "R003")
    )
    return {"finding": {"record": record, "options": {"explanation": provenance}}}


def render(payload: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    """Run the shipped renderers over ``payload`` and report what a browser would show."""
    source = tmp_path / "payload.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    return json.loads(run_node(str(HARNESS), str(source)))


def provenance(**overrides: Any) -> dict[str, Any]:
    """One provenance entry as the API serves it, with the fields under test replaced."""
    entry: dict[str, Any] = {
        "rule_id": "R003",
        "seq": 3,
        "source": SOURCE_DETERMINISTIC,
        "provider": "template",
        "rewritten": True,
        "fallback_used": False,
        "rejection_reasons": [],
        "declined_reason": None,
    }
    entry.update(overrides)
    return entry


@requires_node
def test_the_marker_says_which_text_a_reviewer_is_reading(tmp_path: Path) -> None:
    """Deterministic, model-assisted and fallback are distinguishable on the page."""
    deterministic = render(finding_payload(provenance()), tmp_path)["text"]
    assert "deterministic wording" in deterministic
    assert "model-assisted" not in deterministic

    model_assisted = render(
        finding_payload(provenance(source=SOURCE_MODEL, provider="model")), tmp_path
    )["text"]
    assert "model-assisted wording" in model_assisted
    assert "the engine's status is unchanged" in model_assisted

    fell_back = render(
        finding_payload(
            provenance(provider="model", fallback_used=True, rejection_reasons=["endpoint refused"])
        ),
        tmp_path,
    )["text"]
    assert "fallback" in fell_back
    assert "the deterministic text is being shown" in fell_back
    assert "endpoint refused" in fell_back

    unrecorded = render(finding_payload(None), tmp_path)["text"]
    assert "provenance: not recorded" in unrecorded


@requires_node
def test_the_marker_is_text_even_when_it_quotes_a_models_output(tmp_path: Path) -> None:
    """A rejection reason can carry a model's malformed output; it stays characters."""
    rendered = render(
        finding_payload(
            provenance(
                source=SOURCE_MODEL,
                provider=SCRIPT_PAYLOAD,
                fallback_used=True,
                rejection_reasons=[f"model output is not JSON: {SCRIPT_PAYLOAD}"],
            )
        ),
        tmp_path,
    )
    assert "script" not in rendered["elements"]
    assert "<script" not in rendered["html"]
    assert "&lt;script&gt;alert('model-output')&lt;/script&gt;" in rendered["html"]
    assert SCRIPT_PAYLOAD in rendered["text"]
