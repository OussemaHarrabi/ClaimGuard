"""Read-only evaluation of the organizer's delivered synthetic claim splits.

Gold labels are conformance checks only. The model receives our actual engine
finding and rule, not a gold answer or a fabricated explanation target.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from claimguard.benchmark.corpus import fingerprint
from claimguard.edu.engine import evaluate_claim
from claimguard.edu.envelope import ResultRecord, validate_transport
from claimguard.edu.evidence import resolve
from claimguard.edu.policy import RuleContext


def starter_cases(pack: Path, split: str, context: RuleContext) -> list[dict[str, Any]]:
    """Require exact gold pair coverage and agreement on scored result fields."""
    if split not in ("development", "validation", "stress"):
        raise ValueError("Unknown starter split")
    folder = pack / "data" / split
    claims = [
        json.loads(line)
        for line in (folder / "claims.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]
    records = [
        json.loads(line)
        for line in (folder / "expected_results.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]
    gold = {(row["claim_id"], row["rule_id"]): row for row in records}
    if len(gold) != len(records) or len({claim["claim_id"] for claim in claims}) != len(claims):
        raise ValueError("Gold coverage contains duplicate identifiers")
    expected = {(claim["claim_id"], f"R{index:03}") for claim in claims for index in range(1, 16)}
    if set(gold) != expected:
        raise ValueError("Gold coverage must contain exactly 15 results per claim")
    fields = (
        "status",
        "severity",
        "rule_version",
        "requires_human_review",
        "confidence",
        "confidence_kind",
    )
    cases: list[dict[str, Any]] = []
    source_hash = fingerprint({"claims": claims, "gold": records})
    for claim in claims:
        validate_transport(claim)
        for result in evaluate_claim(claim, context):
            finding = dict(result)
            key = (claim["claim_id"], finding["rule_id"])
            differences = [field for field in fields if finding.get(field) != gold[key].get(field)]
            if differences:
                raise ValueError(f"Gold disagreement {key}: {differences}")
            # The organizer accepts different relevant evidence pointers. Check
            # integrity against the original envelope, not byte-equality to gold.
            for record in (finding, gold[key]):
                ResultRecord.model_validate(record)
                for evidence in record["evidence"]:
                    if fingerprint(resolve(claim, evidence["path"])) != fingerprint(
                        evidence["value"]
                    ):
                        raise ValueError(f"Evidence integrity failed {key}")
                if not set(record["affected_line_ids"]) <= {
                    line["line_id"] for line in claim["lines"]
                }:
                    raise ValueError(f"Unknown affected line {key}")
            policy = context.policy(claim["policy_id"])
            case = {
                "case_id": f"STARTER-{split}-{claim['claim_id']}-{finding['rule_id']}",
                "family": f"starter-{split}-{claim['claim_id']}",
                "split": "screen" if split == "development" else "release",
                "source_split": split,
                "source_hash": source_hash,
                "envelope": claim,
                "finding": finding,
                "rule": context.rule(finding["rule_id"]).model_dump(),
                "policy": policy.model_dump() if policy else {},
                "corpus_version": "organizer-starter-1.0.0",
            }
            case["case_hash"] = fingerprint(case)
            cases.append(case)
    return cases


def stratified_cases(cases: Sequence[dict[str, Any]], *, per_stratum: int) -> list[dict[str, Any]]:
    """Equal deterministic rule/status coverage, without manufacturing rare cases.

    Zero returns the complete input. Selection order is content-addressed rather
    than the source's easy-case prefix. These synthetic records are not proof of
    independent clinical sampling, even when they have distinct claim IDs.
    """
    if per_stratum < 0:
        raise ValueError("per_stratum cannot be negative")
    if not per_stratum:
        return list(cases)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        groups[(case["finding"]["rule_id"], case["finding"]["status"])].append(case)
    ordered = {
        key: sorted(values, key=lambda case: case["case_hash"]) for key, values in groups.items()
    }
    return [
        ordered[key][index]
        for index in range(per_stratum)
        for key in sorted(ordered)
        if index < len(ordered[key])
    ]
