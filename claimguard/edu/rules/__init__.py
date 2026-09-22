"""The 15 deterministic checks, registered in scorer order R001..R015.

Each rule is a pure function ``(claim, ctx) -> result record``; the registry is
the single place that fixes their order, so :mod:`claimguard.edu.engine` can
emit exactly 15 records per claim (docs/04_Rulebook.md:8).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from claimguard.edu.envelope import Claim, Result
from claimguard.edu.policy import RuleContext
from claimguard.edu.rules.r001_r007 import r001, r002, r003, r004, r005, r006, r007
from claimguard.edu.rules.r008_r015 import r008, r009, r010, r011, r012, r013, r014, r015

RuleFn = Callable[[Claim, RuleContext], Result]

#: ``(rule_id, implementation)`` pairs in the order required by the scorer.
RULE_FUNCTIONS: Final[tuple[tuple[str, RuleFn], ...]] = (
    ("R001", r001),
    ("R002", r002),
    ("R003", r003),
    ("R004", r004),
    ("R005", r005),
    ("R006", r006),
    ("R007", r007),
    ("R008", r008),
    ("R009", r009),
    ("R010", r010),
    ("R011", r011),
    ("R012", r012),
    ("R013", r013),
    ("R014", r014),
    ("R015", r015),
)

#: The implementations alone, in R001..R015 order.
ALL_RULES: Final[tuple[RuleFn, ...]] = tuple(function for _, function in RULE_FUNCTIONS)

__all__ = ["ALL_RULES", "RULE_FUNCTIONS", "RuleFn"]
