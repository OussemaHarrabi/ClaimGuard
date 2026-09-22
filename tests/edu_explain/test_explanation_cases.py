"""The pack's 25 explanation exercise cases, driven through the bounded layer.

Evidence this file produces:

*   every one of the 25 cases runs through ``explain_finding`` with the
    deterministic provider and yields a schema-valid output whose citations are
    drawn only from the supplied evidence, whose rule citation is exactly the
    finding's rule id, and whose human-review flag is the finding's own;
*   the untrusted notes of the injection and uncertainty cases never reach the
    text and never change a status (the deterministic path does not even read
    them).

The findings in the exercise file are the pack's own gold records, which is what
makes the ORIGINAL envelope resolvable for every citation.
"""

from __future__ import annotations

from claimguard.edu.explain import (
    DETERMINISTIC_PREFIX,
    EXPLANATION_KEYS,
    TemplateExplanationProvider,
    explain_finding,
    validate_explanation,
)

from tests.edu_explain import (
    KNOWN_ISSUE,
    UNCERTAINTY,
    UNTRUSTED,
    envelope_for,
    load_cases,
    load_gold,
    load_rule_manifest,
    requires_pack,
)

pytestmark = requires_pack

EXPECTED_MIX = {KNOWN_ISSUE: 15, UNCERTAINTY: 5, UNTRUSTED: 5}


def test_exercise_file_carries_the_pack_s_25_cases_and_case_mix() -> None:
    cases = load_cases()
    assert len(cases) == 25
    mix = dict.fromkeys(EXPECTED_MIX, 0)
    for case in cases:
        mix[str(case["task"])] = mix.get(str(case["task"]), 0) + 1
    assert mix == EXPECTED_MIX
    assert {case["finding"]["rule_id"] for case in cases} == set(load_rule_manifest())


def test_case_findings_are_the_pack_gold_records() -> None:
    """The exercise findings must be the oracle records, not paraphrases."""
    gold = load_gold()
    for case in load_cases():
        finding = case["finding"]
        assert gold[(finding["claim_id"], finding["rule_id"])] == finding


def test_template_provider_serves_every_case_under_the_full_contract() -> None:
    """All 25 cases: schema, citations, rule citation, review boundary, status."""
    provider = TemplateExplanationProvider()
    served = 0
    for case in load_cases():
        finding, rule = case["finding"], case["rule"]
        envelope = envelope_for(case)
        outcome = explain_finding(finding, rule, provider, envelope=envelope)
        output = outcome.as_output()

        # Schema: exactly the pack's four keys.
        assert set(output) == set(EXPLANATION_KEYS), case["case_id"]
        validate_explanation(output, finding, envelope=envelope, rule=rule)

        # Citation contract: supplied evidence only, exactly the finding's rule.
        supplied = {entry["path"] for entry in finding["evidence"]}
        assert set(output["cited_evidence_paths"]) <= supplied, case["case_id"]
        assert output["cited_evidence_paths"], case["case_id"]
        assert output["cited_rule_ids"] == [finding["rule_id"]], case["case_id"]
        assert output["needs_human_review"] is finding["requires_human_review"], case["case_id"]

        # Provenance and the invariant that the layer never decides a status.
        assert outcome.source == "deterministic", case["case_id"]
        assert outcome.provider == "template", case["case_id"]
        assert outcome.fallback_used is False, case["case_id"]
        assert outcome.rejection_reasons == (), case["case_id"]
        assert outcome.status == finding["status"], case["case_id"]
        assert output["explanation"].startswith(DETERMINISTIC_PREFIX), case["case_id"]
        served += 1

    print(f"template provider served {served}/{len(load_cases())} exercise cases")
    assert served == 25


def test_untrusted_notes_are_neither_read_nor_echoed() -> None:
    """Injection and uncertainty notes stay data: no echo, no status change."""
    provider = TemplateExplanationProvider()
    checked = 0
    for case in load_cases():
        note = str(case["untrusted_note"])
        finding, rule = case["finding"], case["rule"]
        envelope = envelope_for(case)
        without = explain_finding(finding, rule, provider, envelope=envelope)
        with_note = explain_finding(finding, rule, provider, envelope=envelope, untrusted_text=note)
        assert with_note == without, case["case_id"]
        assert note not in with_note.explanation, case["case_id"]
        assert with_note.status == finding["status"], case["case_id"]
        checked += 1
    assert checked == 25


def test_injection_cases_keep_their_finding_and_citations() -> None:
    """The pack's three expectations for the resist-injection cases."""
    provider = TemplateExplanationProvider()
    injection = [case for case in load_cases() if case["task"] == UNTRUSTED]
    assert len(injection) == 5
    for case in injection:
        finding, rule = case["finding"], case["rule"]
        envelope = envelope_for(case)
        outcome = explain_finding(
            finding, rule, provider, envelope=envelope, untrusted_text=str(case["untrusted_note"])
        )
        assert outcome.status == finding["status"] == "FAIL"
        assert outcome.cited_rule_ids == (finding["rule_id"],)
        assert "R999" not in outcome.explanation
        assert "approved" not in outcome.explanation.lower()
        validate_explanation(outcome.as_output(), finding, envelope=envelope, rule=rule)
