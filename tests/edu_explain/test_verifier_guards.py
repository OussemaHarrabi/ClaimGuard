"""Guard tests for the explanation verifier (pack-independent).

The pack's ``validate_explanation`` checks the shape of the output; the pack's own
prose then asks for more (``prompts/explain_findings.md``: "Do not approve
payment, infer clinical necessity, accuse anyone of fraud"; ``docs/05``: "verify
that all citations refer to supplied inputs"). These tests pin the guards that
implement the extra checks, and pin the *negative* control: quoting an evidence
value such as ``"denied"`` is data and must stay acceptable, while asserting a
decision must not.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from claimguard.edu.explain import (
    DETERMINISTIC_PREFIX,
    EXPLANATION_KEYS,
    ExplanationRejectionError,
    TemplateExplanationProvider,
    explain_finding,
    validate_explanation,
)

from tests.edu_explain import (
    SYNTHETIC_ENVELOPE,
    SYNTHETIC_RULE,
    StubModelProvider,
    synthetic_finding,
)

DECISION_OUTPUT = "The claim is approved for payment."


def candidate(finding: Mapping[str, Any], **overrides: Any) -> dict[str, Any]:
    """A contract-clean candidate output for ``finding``, with targeted overrides."""
    output: dict[str, Any] = {
        "explanation": (
            "The billed quantity 1.5 is not a positive integer, so the fictional limit "
            "cannot be satisfied."
        ),
        "cited_evidence_paths": ["/lines/0/quantity"],
        "cited_rule_ids": [finding["rule_id"]],
        "needs_human_review": finding["requires_human_review"],
    }
    output.update(overrides)
    return output


# ---------------------------------------------------------------------------
# Accepted controls
# ---------------------------------------------------------------------------


def test_a_clean_candidate_is_accepted_and_returned_with_exactly_four_keys() -> None:
    finding = synthetic_finding()
    validated = validate_explanation(
        candidate(finding), finding, envelope=SYNTHETIC_ENVELOPE, rule=SYNTHETIC_RULE
    )
    assert set(validated) == set(EXPLANATION_KEYS)
    assert validated["cited_rule_ids"] == ["R013"]


def test_quoting_an_evidence_value_is_data_not_a_decision() -> None:
    """`/authorizations/0/status = "denied"` is an observation, not an assertion."""
    finding = synthetic_finding(
        evidence=[{"path": "/authorizations/0/status", "value": "denied"}],
    )
    envelope = {
        "claim_id": "CG-SYNTHETIC-0001",
        "authorizations": [{"authorization_id": "A1", "status": "denied"}],
    }
    validated = validate_explanation(
        candidate(
            finding,
            explanation=(
                'The authorization status observed at /authorizations/0/status is "denied", '
                "so the referenced authorization cannot be honoured."
            ),
            cited_evidence_paths=["/authorizations/0/status"],
        ),
        finding,
        envelope=envelope,
        rule=SYNTHETIC_RULE,
    )
    assert "denied" in validated["explanation"]


# ---------------------------------------------------------------------------
# Rejections: the pack's contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "fragment", "overrides"),
    [
        (
            "evidence path not supplied with the finding",
            "was not supplied with the finding",
            {"cited_evidence_paths": ["/lines/0/secret_price"]},
        ),
        (
            "rule citation is not exactly the finding's rule",
            "cited_rule_ids must be exactly",
            {"cited_rule_ids": ["R999"]},
        ),
        (
            "human-review boundary changed",
            "must equal the finding's requires_human_review",
            {"needs_human_review": False},
        ),
        ("empty explanation", "non-empty string", {"explanation": "   "}),
        (
            "explanation merely repeats the rule text",
            "merely repeats the rule text",
            {"explanation": SYNTHETIC_RULE["logic"]},
        ),
        (
            "extra key beyond the four",
            "keys must be exactly",
            {"confidence": 0.93},
        ),
        (
            "citations are not a list of strings",
            "non-empty list of strings",
            {"cited_evidence_paths": "/lines/0/quantity"},
        ),
        (
            "human-review flag is not a boolean",
            "must be a boolean",
            {"needs_human_review": "yes"},
        ),
        (
            "empty rule citation list",
            "cited_rule_ids must be exactly",
            {"cited_rule_ids": []},
        ),
    ],
)
def test_contract_breaches_are_rejected(
    label: str, fragment: str, overrides: dict[str, Any]
) -> None:
    finding = synthetic_finding()
    with pytest.raises(ExplanationRejectionError) as caught:
        validate_explanation(
            candidate(finding, **overrides),
            finding,
            envelope=SYNTHETIC_ENVELOPE,
            rule=SYNTHETIC_RULE,
        )
    assert fragment in "; ".join(caught.value.reasons), label


def test_non_object_output_is_rejected() -> None:
    with pytest.raises(ExplanationRejectionError):
        validate_explanation(["not", "an", "object"], synthetic_finding())


# ---------------------------------------------------------------------------
# Rejections: the guards the pack's prose requires
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "prohibited", "text"),
    [
        ("approval", "adjudication_outcome", DECISION_OUTPUT),
        ("denial", "adjudication_outcome", "The claim will be denied by the payer."),
        ("payment", "adjudication_outcome", "This invoice is paid in full."),
        ("clinical necessity", "clinical_judgement", "The service is medically necessary."),
        ("fraud accusation", "fraud_accusation", "This pattern looks like fraud."),
        ("payment guarantee", "payment_guarantee", "We guarantee payment after review."),
    ],
)
def test_adjudication_and_clinical_assertions_are_rejected(
    label: str, prohibited: str, text: str
) -> None:
    finding = synthetic_finding()
    with pytest.raises(ExplanationRejectionError) as caught:
        validate_explanation(
            candidate(finding, explanation=text),
            finding,
            envelope=SYNTHETIC_ENVELOPE,
            rule=SYNTHETIC_RULE,
        )
    reasons = "; ".join(caught.value.reasons)
    assert "explains, it never decides" in reasons, label
    assert prohibited in reasons, label


def test_every_breach_is_reported_at_once() -> None:
    """Reasons are a list: the reviewer report has to explain the whole rejection."""
    finding = synthetic_finding()
    with pytest.raises(ExplanationRejectionError) as caught:
        validate_explanation(
            candidate(
                finding,
                explanation=DECISION_OUTPUT,
                cited_evidence_paths=["/lines/9/unit_price"],
                cited_rule_ids=["R014"],
                needs_human_review=False,
            ),
            finding,
            envelope=SYNTHETIC_ENVELOPE,
            rule=SYNTHETIC_RULE,
        )
    assert len(caught.value.reasons) >= 4


# ---------------------------------------------------------------------------
# Rejections: citations must resolve in the ORIGINAL envelope
# ---------------------------------------------------------------------------


def test_citation_that_does_not_resolve_in_the_envelope_is_rejected() -> None:
    finding = synthetic_finding()
    empty_envelope: dict[str, Any] = {"claim_id": "CG-SYNTHETIC-0001", "lines": []}
    with pytest.raises(ExplanationRejectionError, match="does not resolve in the original"):
        validate_explanation(candidate(finding), finding, envelope=empty_envelope)


def test_citation_from_another_claim_s_envelope_is_rejected() -> None:
    finding = synthetic_finding()
    other = {**SYNTHETIC_ENVELOPE, "claim_id": "CG-OTHER-0002"}
    with pytest.raises(ExplanationRejectionError, match="belongs to 'CG-OTHER-0002'"):
        validate_explanation(candidate(finding), finding, envelope=other)


def test_citation_whose_value_was_rewritten_is_rejected() -> None:
    finding = synthetic_finding(evidence=[{"path": "/lines/0/unit_price", "value": 999}])
    with pytest.raises(ExplanationRejectionError, match="not to the stored value"):
        validate_explanation(
            candidate(finding, cited_evidence_paths=["/lines/0/unit_price"]),
            finding,
            envelope=SYNTHETIC_ENVELOPE,
        )


def test_without_an_envelope_only_the_supplied_path_set_is_enforced() -> None:
    """``envelope`` is optional; the pack's subset rule still applies without it."""
    finding = synthetic_finding()
    validated = validate_explanation(candidate(finding), finding)
    assert validated["cited_evidence_paths"] == ["/lines/0/quantity"]
    with pytest.raises(ExplanationRejectionError):
        validate_explanation(
            candidate(finding, cited_evidence_paths=["/lines/0/elsewhere"]), finding
        )


# ---------------------------------------------------------------------------
# Rejection → marked deterministic fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "output_text",
    ["The claim is approved for payment.", "The diagnosis confirms clinical necessity."],
)
def test_rejected_model_output_falls_back_and_is_marked(output_text: str) -> None:
    finding = synthetic_finding()
    provider = StubModelProvider(
        output=candidate(finding, explanation=output_text),
    )
    outcome = explain_finding(finding, SYNTHETIC_RULE, provider, envelope=SYNTHETIC_ENVELOPE)
    assert provider.calls == [(finding["claim_id"], "R013")], "the provider was consulted"
    assert outcome.fallback_used is True
    assert outcome.source == "deterministic"
    assert outcome.explanation.startswith(DETERMINISTIC_PREFIX)
    assert outcome.status == finding["status"]
    assert outcome.needs_human_review is finding["requires_human_review"]
    assert outcome.rejection_reasons
    validate_explanation(
        outcome.as_output(), finding, envelope=SYNTHETIC_ENVELOPE, rule=SYNTHETIC_RULE
    )
    print(f"REJECTED model output: {output_text!r}")
    print(f"    reasons: {list(outcome.rejection_reasons)}")
    print(f"    shown instead: {outcome.explanation[:90]}...")


def test_fabricated_citation_falls_back_with_the_fabrication_named() -> None:
    finding = synthetic_finding()
    provider = StubModelProvider(
        output=candidate(finding, cited_evidence_paths=["/lines/0/imaginary_field"])
    )
    outcome = explain_finding(finding, SYNTHETIC_RULE, provider, envelope=SYNTHETIC_ENVELOPE)
    assert outcome.fallback_used is True
    assert any("/lines/0/imaginary_field" in reason for reason in outcome.rejection_reasons)


def test_a_manifest_that_asserts_a_decision_cannot_poison_the_fallback() -> None:
    """Even a poisoned rule excerpt degrades to a clean deterministic text.

    A record whose own corrective action is empty (an engine PASS) takes the
    reviewer step from the manifest, so manifest wording reaches the text: if a
    future rulebook asserted a decision there, the guard rejects the text and the
    citation-only fallback is used instead.
    """
    finding = synthetic_finding(status="PASS", corrective_action="", requires_human_review=False)
    poisoned_rule = dict(SYNTHETIC_RULE)
    poisoned_rule["corrective_action"] = "Inform the payer that the claim is approved."
    provider = TemplateExplanationProvider()
    outcome = explain_finding(finding, poisoned_rule, provider, envelope=SYNTHETIC_ENVELOPE)
    assert outcome.source == "deterministic"
    assert outcome.status == finding["status"]
    assert outcome.needs_human_review is False
    assert "approved" not in outcome.explanation.lower()
    assert any("never decides" in reason for reason in outcome.rejection_reasons)
    validate_explanation(
        outcome.as_output(), finding, envelope=SYNTHETIC_ENVELOPE, rule=poisoned_rule
    )
