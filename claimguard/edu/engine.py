"""Engine: run the 15 deterministic checks over one claim.

The engine is the only place that fixes result *coverage*: exactly one record
per rule, in R001..R015 order, for every claim
(docs/04_Rulebook.md:8; docs/07_Evaluation_and_Acceptance.md — "The scorer
requires every claim-rule pair exactly once").
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from claimguard.edu.envelope import Claim, Result
from claimguard.edu.policy import RuleContext
from claimguard.edu.rules import ALL_RULES, RULE_FUNCTIONS


@dataclass(frozen=True)
class RunSummary:
    """Counts the CLI reports after a run."""

    records: int
    by_rule: dict[str, int]
    by_status: dict[str, int]


def evaluate_claim(claim: Claim, ctx: RuleContext) -> list[Result]:
    """Evaluate one claim envelope and return its 15 records in R001..R015 order."""
    return [function(claim, ctx) for function in ALL_RULES]


def evaluate_claims(claims: Iterable[Claim], ctx: RuleContext) -> Iterator[Result]:
    """Evaluate many claims, yielding 15 records per claim in claim order."""
    for claim in claims:
        yield from evaluate_claim(claim, ctx)


def expected_rule_ids() -> tuple[str, ...]:
    """The rule ids produced per claim — the scorer's coverage contract."""
    return tuple(rule_id for rule_id, _ in RULE_FUNCTIONS)


def summarize(records: Sequence[Result]) -> RunSummary:
    """Count records per rule and per status, for a run report on stderr."""
    by_rule: dict[str, int] = dict.fromkeys(expected_rule_ids(), 0)
    by_status: dict[str, int] = {}
    for record in records:
        rule_id = str(record["rule_id"])
        by_rule[rule_id] = by_rule.get(rule_id, 0) + 1
        status = str(record["status"])
        by_status[status] = by_status.get(status, 0) + 1
    return RunSummary(records=len(records), by_rule=by_rule, by_status=by_status)
