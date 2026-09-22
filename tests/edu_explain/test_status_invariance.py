"""Required MVP behaviour 6: a model failure cannot remove or change a finding.

The engine's 15 records per claim are enriched with a deterministic provider, an
absent model, a failing model, a malformed model and two adversarial models
(fabricated citations, authorised payment). In every run the only field allowed
to differ is ``explanation``; every status, severity, evidence entry, corrective
action and review flag must be byte-for-byte identical, and the enriched record
must still satisfy the frozen result contract (15 keys, evidence re-resolving
against the original envelope).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from claimguard.edu.emit import validate_record
from claimguard.edu.engine import evaluate_claim
from claimguard.edu.envelope import RESULT_KEYS
from claimguard.edu.explain import (
    ENV_BASE_URL,
    ENV_MODEL,
    ModelExplanationProvider,
    ModelSettings,
    TemplateExplanationProvider,
    apply_outcomes,
    explain_records,
)

from tests.edu import base_claim, rules_context
from tests.edu_explain import (
    UNTRUSTED,
    StubModelProvider,
    load_cases,
    load_claims,
    requires_pack,
    synthetic_finding,
)

IMMUTABLE_FIELDS = tuple(key for key in RESULT_KEYS if key != "explanation")


def _strip_explanations(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in record.items() if key != "explanation"} for record in records
    ]


def _providers(finding: Mapping[str, Any]) -> dict[str, Any]:
    """Every provider shape the layer must survive, keyed by label."""
    fabricated = {
        "explanation": "The quantity is fine and the claim can proceed.",
        "cited_evidence_paths": ["/lines/0/imaginary"],
        "cited_rule_ids": [finding["rule_id"]],
        "needs_human_review": finding["requires_human_review"],
    }
    approved = {
        "explanation": "The claim is approved for payment.",
        "cited_evidence_paths": ["/lines/0/quantity"],
        "cited_rule_ids": [finding["rule_id"]],
        "needs_human_review": finding["requires_human_review"],
    }
    return {
        "template": TemplateExplanationProvider(),
        "absent": None,
        "failing": StubModelProvider(error=TimeoutError("upstream slow")),
        "malformed": StubModelProvider(error=ValueError("not JSON")),
        "fabricated_citation": StubModelProvider(output=fabricated),
        "authorised_payment": StubModelProvider(output=approved),
    }


def _assert_only_the_explanation_moved(
    records: Sequence[Mapping[str, Any]],
    enriched: Sequence[Mapping[str, Any]],
    claim: Any,
    label: str,
) -> None:
    assert len(enriched) == len(records), label
    for original, updated in zip(records, enriched, strict=True):
        assert set(updated) == set(RESULT_KEYS), label
        for field in IMMUTABLE_FIELDS:
            assert updated[field] == original[field], f"{label}: {field} changed"
        assert updated["explanation"].strip(), label
        validate_record(updated, claim)
    assert _strip_explanations(records) == _strip_explanations(enriched), label


def test_no_provider_shape_can_move_a_status_on_a_synthetic_claim() -> None:
    """Pack-independent: the engine's own 15 records, every provider fault."""
    claim = base_claim()
    context = rules_context()
    records = evaluate_claim(claim, context)
    for label, provider in _providers(records[0]).items():
        outcomes = explain_records(records, context, provider, envelope=claim)
        enriched = apply_outcomes(records, outcomes)
        _assert_only_the_explanation_moved(records, enriched, claim, label)
        print(f"{label}: {len(enriched)} records enriched, 0 immutable fields changed")


@requires_pack
def test_no_provider_shape_can_move_a_status_across_the_exercise_claims() -> None:
    """The 25 exercise claims, including the five injection stress cases."""
    context = rules_context()
    claims = load_claims()
    checked = 0
    for case in load_cases():
        finding = case["finding"]
        claim = claims[finding["claim_id"]]
        records = evaluate_claim(claim, context)
        assert len(records) == 15
        for label, provider in _providers(finding).items():
            outcomes = explain_records(records, context, provider, envelope=claim)
            enriched = apply_outcomes(records, outcomes)
            _assert_only_the_explanation_moved(records, enriched, claim, label)
        checked += 1
    print(
        f"status invariance: {checked} claims x 6 provider shapes x 15 records = "
        f"{checked * 6 * 15} enrichments, 0 immutable fields changed"
    )
    assert checked == 25


@requires_pack
def test_injected_attachment_text_never_reaches_an_explanation_or_a_status() -> None:
    """The stress claims carry instruction-like attachment text; it stays data."""
    context = rules_context()
    claims = load_claims()
    injection_cases = [case for case in load_cases() if case["task"] == UNTRUSTED]
    assert len(injection_cases) == 5
    notes_checked = 0
    for case in injection_cases:
        claim = claims[case["finding"]["claim_id"]]
        records = evaluate_claim(claim, context)
        outcomes = explain_records(
            records,
            context,
            TemplateExplanationProvider(),
            envelope=claim,
            untrusted_text=str(case["untrusted_note"]),
        )
        enriched = apply_outcomes(records, outcomes)
        _assert_only_the_explanation_moved(records, enriched, claim, str(case["case_id"]))
        for reader in enriched:
            text = str(reader["explanation"]).lower()
            assert "ignore the rulebook" not in text
            assert "api key" not in text
            assert "r999" not in text
        notes_checked += len(enriched)
    print(
        f"injected attachment/note text: {len(injection_cases)} claims, "
        f"{notes_checked} explanations checked, none echo the injection"
    )


def test_the_layer_leaves_records_without_citable_evidence_alone() -> None:
    """No evidence pointer means no contract-valid explanation; the record stands."""
    finding = synthetic_finding(
        evidence=[],
        status="NOT_IMPLEMENTED",
        requires_human_review=False,
        corrective_action="",
    )
    empty = {"claim_id": finding["claim_id"]}
    outcomes = explain_records([finding], {"R013": {}}, None, envelope=empty)
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.rewritten is False
    assert outcome.declined_reason is not None
    assert outcome.explanation == finding["explanation"]
    assert apply_outcomes([finding], outcomes)[0] == finding


def test_a_model_provider_is_never_consulted_for_a_passing_rule() -> None:
    """Cost and scope bound: only FAIL / UNABLE_TO_ASSESS are sent to a model."""
    claim = base_claim()
    context = rules_context()
    records = evaluate_claim(claim, context)
    provider = StubModelProvider(output={})
    outcomes = explain_records(records, context, provider, envelope=claim)
    statuses = {str(record["status"]) for record in records}
    assert statuses == {"PASS", "NOT_APPLICABLE"}, "the base claim is clean"
    assert provider.calls == [], "a passing record must never cost a model call"
    assert all(outcome.declined_reason is not None for outcome in outcomes)
    assert all(outcome.source == "deterministic" for outcome in outcomes)
    assert apply_outcomes(records, outcomes) != []  # records survive untouched


def test_a_configured_model_is_consulted_only_for_flagged_records() -> None:
    """With a model configured, flagged records call it and passes do not."""
    claim = base_claim()
    claim["lines"][0]["quantity"] = 1.5  # a non-integer quantity breaks the price rules
    context = rules_context()
    records = evaluate_claim(claim, context)
    flagged = {
        str(record["rule_id"])
        for record in records
        if str(record["status"]) in {"FAIL", "UNABLE_TO_ASSESS"}
    }
    assert flagged, "the mutated claim must have at least one flagged rule"

    provider = _CapturingProvider()
    outcomes = explain_records(records, context, provider, envelope=claim)
    assert {call[1] for call in provider.calls} == flagged
    for outcome in outcomes:
        if outcome.rule_id in flagged:
            assert outcome.fallback_used is True, "the stub answers with nothing usable"
            assert outcome.source == "deterministic"
        else:
            assert outcome.declined_reason is not None


class _CapturingProvider:
    """A model provider that answers with an empty object, recording the calls."""

    name = "capturing"
    source_kind = "model"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def explain(
        self,
        finding: Mapping[str, Any],
        rule: Mapping[str, Any],
        *,
        untrusted_text: str | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append((str(finding.get("claim_id")), str(finding.get("rule_id"))))
        return {}


def test_a_configured_but_shapeless_environment_still_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half-configured deployments (URL without model) take the deterministic path."""
    monkeypatch.setenv(ENV_BASE_URL, "http://127.0.0.1:1234/v1")
    monkeypatch.delenv(ENV_MODEL, raising=False)
    assert ModelExplanationProvider.from_env() is None
    assert ModelSettings.from_env() is None
