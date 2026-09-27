"""Adversarial boundary cases, pinned so the engine's edges cannot drift.

``scripts/adversarial_cases.py`` holds the cases and the runner; this module makes
them part of the suite. The value is in what the cases are: each one states a
boundary the rulebook words precisely - "both inclusive", "at most 0.01 SAR",
"equality at the maximum passes" - and asserts the exact status that wording
requires. A regression that loosened R007's tolerance or made R009's dates
exclusive would come back as a mismatch here, not as a silent scoring loss.

The pack's own splits are representative rather than adversarial, so they would
not catch those. Neither would a smoke test: these cases are cheap (no database,
no pack dataset, ~0.1s for all of them) and they run against the vendored
catalogue, so CI covers them.

The cases also cover the two layers below the rules:

*   the transport contract, which refuses a malformed envelope BEFORE any rule
    runs - including the structural keys (``provider_id``, ``submission_date``,
    ``currency``) whose null is a defect by design, unlike the business values
    (``member_id``, ``invoice_number``, ``diagnosis_code``, line ``service_date``,
    ``unit_price``) that stay nullable so the rules can abstain on them; and
*   robustness: 100k-character notes, markup and control characters, 200 lines,
    1e12 amounts, year 1900 and 9999, emoji identifiers, a 10k-character service
    code. Each must still yield exactly 15 records that satisfy the emitted-record
    contract against the original object.
"""

from __future__ import annotations

import pytest
from claimguard.edu.policy import RuleContext
from scripts.adversarial_cases import all_cases, run_case

from tests.edu import RULES_DIR

pytestmark = pytest.mark.unit


def test_every_adversarial_case_matches_the_rulebook() -> None:
    """One mismatch - a false negative or a false positive - fails this test."""
    context = RuleContext.from_rules_dir(RULES_DIR)
    cases = all_cases()
    assert len(cases) >= 80, "the case list shrank; that is a loss of coverage, not a pass"

    outcomes = [run_case(case, context) for case in cases]
    bad = [outcome for outcome in outcomes if outcome.verdict != "OK"]
    report = "\n".join(
        f"  {outcome.case.name}: expected {outcome.case.expected}, got "
        f"{outcome.observed} ({outcome.detail})"
        for outcome in bad
    )
    assert not bad, f"{len(bad)} of {len(cases)} adversarial cases did not behave:\n{report}"


def test_the_case_list_covers_every_rule() -> None:
    """A rule with no boundary case is a rule whose edges nobody checked."""
    from claimguard.edu.envelope import RULE_IDS

    covered = {case.rule for case in all_cases() if case.rule is not None}
    assert covered == set(RULE_IDS), (
        f"rules without an adversarial case: {sorted(set(RULE_IDS) - covered)}"
    )


def test_robustness_cases_still_return_fifteen_valid_records() -> None:
    """The hostile payloads specifically: no crash, and the contract still holds."""
    context = RuleContext.from_rules_dir(RULES_DIR)
    robustness = [case for case in all_cases() if case.name.startswith("robust:")]
    assert robustness, "the robustness group is gone"

    for case in robustness:
        outcome = run_case(case, context)
        assert outcome.verdict == "OK", f"{case.name}: {outcome.verdict} - {outcome.detail}"
