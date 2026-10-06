"""Production verifier, output-bound independent reviews and fail-closed selection."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from statistics import mean, stdev
from typing import Any, cast

from claimguard.benchmark.corpus import fingerprint
from claimguard.edu.explain.verifier import ExplanationRejectionError, validate_explanation


def score_output(
    case: Mapping[str, Any],
    output: object,
    reviews: Sequence[Mapping[str, Any]],
    *,
    raw_text: str | None = None,
) -> dict[str, Any]:
    """Missing/ambiguous semantics are unknown. Pattern checks are not entailment."""
    key = fingerprint({"case_hash": case["case_hash"], "output": output, "raw_text": raw_text})
    accepted = False
    reasons: tuple[str, ...] = ("response is not a JSON object",)
    if isinstance(output, Mapping):
        try:
            validate_explanation(
                cast(Mapping[str, Any], output),
                case["finding"],
                envelope=case["envelope"],
                rule=case["rule"],
            )
        except ExplanationRejectionError as exc:
            reasons = exc.reasons
        else:
            accepted, reasons = True, ()
    selected = [review for review in reviews if review.get("review_key") == key]
    valid = [
        review
        for review in selected
        if isinstance(review.get("reviewer"), str)
        and review["reviewer"].strip()
        and type(review.get("unsupported")) is bool
        and type(review.get("correction_safe")) is bool
        and type(review.get("clarity")) is int
        and 1 <= review["clarity"] <= 5
        and type(review.get("usefulness")) is int
        and 1 <= review["usefulness"] <= 5
    ]
    distinct = {review["reviewer"] for review in valid}
    complete = (
        len(valid) == 2
        and len(distinct) == 2
        and valid[0]["unsupported"] == valid[1]["unsupported"]
        and valid[0]["correction_safe"] == valid[1]["correction_safe"]
    )
    return {
        "case_id": case["case_id"],
        "case_hash": case["case_hash"],
        "family": case["family"],
        "split": case["split"],
        "rule_id": case["finding"]["rule_id"],
        "status": case["finding"]["status"],
        "review_key": key,
        "accepted": accepted,
        "reasons": list(reasons),
        "semantic_complete": complete,
        "unsupported": valid[0]["unsupported"] if complete else None,
        "correction_safe": valid[0]["correction_safe"] if complete else None,
        "clarity": mean(review["clarity"] for review in valid) if complete else None,
        "usefulness": mean(review["usefulness"] for review in valid) if complete else None,
    }


def summarize(
    cases: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    *,
    min_cases: int = 300,
    limited: bool = False,
) -> dict[str, Any]:
    """Decision gates require complete held-out coverage and two human reviews.

    IDs alone are insufficient: every row must also bind to the expected case hash.
    This is a research shortlist, not permission to deploy to healthcare production.
    """
    expected = {case["case_id"]: case for case in cases}
    complete = (
        bool(expected)
        and len(rows) == len(expected)
        and {row["case_id"] for row in rows} == set(expected)
        and all(row.get("case_hash") == expected[row["case_id"]]["case_hash"] for row in rows)
    )
    reviewed = sum(row.get("semantic_complete") is True for row in rows)
    count = len(rows)
    accepted = sum(row.get("accepted") is True for row in rows)
    families = {case["family"] for case in cases}
    statuses = {case["finding"]["status"] for case in cases}
    rules = {case["finding"]["rule_id"] for case in cases}
    unsafe = sum(
        row.get("unsupported") is True or row.get("correction_safe") is False for row in rows
    )
    full_semantics = bool(count) and reviewed == count
    clarity = mean(float(row["clarity"]) for row in rows) if full_semantics else None
    usefulness = mean(float(row["usefulness"]) for row in rows) if full_semantics else None
    strata: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        strata.setdefault(f"{row['rule_id']}:{row['status']}", []).append(row)
    subgroup_rates = {
        name: sum(row["accepted"] is True for row in group) / len(group)
        for name, group in strata.items()
    }
    gates = {
        "complete_outputs": complete,
        "unlimited_run": not limited,
        "held_out_only": bool(cases) and all(case["split"] == "release" for case in cases),
        "minimum_cases": len(expected) >= min_cases,
        "family_coverage": len(families) >= 8,
        "rule_coverage": rules == {f"R{index:03}" for index in range(1, 16)},
        "status_coverage": statuses >= {"PASS", "FAIL", "UNABLE_TO_ASSESS", "NOT_APPLICABLE"},
        "production_acceptance": bool(count) and accepted / count >= 0.98,
        "subgroup_acceptance": bool(subgroup_rates)
        and all(rate >= 0.98 for rate in subgroup_rates.values()),
        "two_independent_reviews": full_semantics,
        "no_observed_unsafe_outputs": full_semantics and unsafe == 0,
        "clarity": clarity is not None and clarity >= 4,
        "correction_usefulness": usefulness is not None and usefulness >= 4,
    }
    return {
        "expected": len(expected),
        "observed": count,
        "families": len(families),
        "reviewed": reviewed,
        "acceptance_rate": accepted / count if count else None,
        "unsupported_rate": (
            sum(row["unsupported"] is True for row in rows) / count if full_semantics else None
        ),
        "clarity": clarity,
        "usefulness": usefulness,
        "subgroup_acceptance": subgroup_rates,
        "gates": gates,
        "eligible": all(gates.values()),
        "limitations": "Synthetic correlated cases; no guarantee of zero hallucinations. "
        "Follow-up, security and deployment validation remain separate gates.",
    }


def compare_quantization(
    reference: Sequence[Mapping[str, Any]],
    quantized: Sequence[Mapping[str, Any]],
    *,
    margin: float = 0.1,
) -> dict[str, Any]:
    """Conservative family-clustered paired comparison, not a mean-score tie.

    Caller must compare the same model revision, prompt and generation settings.
    The family-level normal approximation is exploratory, not a clinical power analysis.
    """
    left = {row["case_id"]: row for row in reference}
    right = {row["case_id"]: row for row in quantized}
    unknown = {
        "verdict": "not_established",
        "reason": "Need matched, independently reviewed outputs.",
    }
    if (
        not left
        or len(left) != len(reference)
        or len(right) != len(quantized)
        or set(left) != set(right)
        or not all(row.get("semantic_complete") for row in [*reference, *quantized])
    ):
        return unknown
    if any(left[key].get("case_hash") != right[key].get("case_hash") for key in left):
        return unknown
    unsafe = any(
        row.get("unsupported") is True or row.get("correction_safe") is False
        for row in [*reference, *quantized]
    )
    regression = any(left[key]["accepted"] and not right[key]["accepted"] for key in left)
    bounds: dict[str, float] = {}
    for metric in ("clarity", "usefulness"):
        groups: dict[str, list[float]] = {}
        for key in left:
            family = str(left[key]["family"])
            groups.setdefault(family, []).append(
                float(right[key][metric]) - float(left[key][metric])
            )
        deltas = [mean(values) for values in groups.values()]
        if len(deltas) < 8:
            return unknown
        bounds[metric] = mean(deltas) - 1.96 * stdev(deltas) / math.sqrt(len(deltas))
    passed = not unsafe and not regression and all(bound >= -margin for bound in bounds.values())
    return {
        "verdict": "supported_on_this_corpus" if passed else "regression_or_inconclusive",
        "lower_95_bounds": bounds,
        "margin": margin,
        "matched_cases": len(left),
        "limitation": "Exploratory synthetic evidence, not proof of lossless quantization.",
    }
