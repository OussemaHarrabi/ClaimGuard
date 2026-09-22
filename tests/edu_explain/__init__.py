"""Shared fixtures for the bounded explanation layer tests (``tests/edu_explain``).

The 25 explanation exercises, their claim envelopes, the gold records and the
rule manifest all live in the mentor pack, which is read-only reference material
(see ``docs/10-ADR-Starter-Pack-Authority.md`` §2.2). They are read here, never
written. Tests that need the pack are marked with ``requires_pack`` so the suite
still runs when the pack is absent.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from tests.edu import PACK_ROOT, requires_pack

__all__ = [
    "CASES_PATH",
    "KNOWN_ISSUE",
    "SPLITS",
    "SYNTHETIC_ENVELOPE",
    "SYNTHETIC_RULE",
    "UNCERTAINTY",
    "UNTRUSTED",
    "StubModelProvider",
    "envelope_for",
    "load_cases",
    "load_claims",
    "load_gold",
    "load_records",
    "load_rule_manifest",
    "requires_pack",
    "synthetic_finding",
]

CASES_PATH = PACK_ROOT / "exercises" / "llm_explanation_cases.jsonl"
SPLITS = ("development", "validation", "stress")

#: Tasks of the exercise file (pack `docs/05_Architecture_and_AI.md`, "AI exercise").
KNOWN_ISSUE = "Explain a known issue"
UNCERTAINTY = "Explain uncertainty"
UNTRUSTED = "Resist untrusted instruction"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Parse a JSONL file into a list of JSON objects (blank lines skipped)."""
    text = path.read_text(encoding="utf-8")
    return [cast("dict[str, Any]", json.loads(line)) for line in text.splitlines() if line.strip()]


@lru_cache(maxsize=1)
def load_cases() -> tuple[dict[str, Any], ...]:
    """The 25 explanation exercise cases, in file order."""
    return tuple(_read_jsonl(CASES_PATH))


@lru_cache(maxsize=1)
def load_rule_manifest() -> Mapping[str, dict[str, Any]]:
    """``rules/rules.json`` keyed by rule id (the manifest the layer excerpted)."""
    entries = cast(
        "list[dict[str, Any]]", json.loads((PACK_ROOT / "rules" / "rules.json").read_text("utf-8"))
    )
    return {entry["rule_id"]: entry for entry in entries}


@lru_cache(maxsize=1)
def load_claims() -> Mapping[str, dict[str, Any]]:
    """Every claim envelope of the three public splits, keyed by claim id."""
    claims: dict[str, dict[str, Any]] = {}
    for split in SPLITS:
        for claim in _read_jsonl(PACK_ROOT / "data" / split / "claims.jsonl"):
            claims[claim["claim_id"]] = claim
    return claims


def load_records(split: str) -> tuple[dict[str, Any], ...]:
    """The gold result records of one public split, in file order."""
    return tuple(_read_jsonl(PACK_ROOT / "data" / split / "expected_results.jsonl"))


@lru_cache(maxsize=1)
def load_gold() -> Mapping[tuple[str, str], dict[str, Any]]:
    """The pack's gold result records of the three public splits, keyed by pair."""
    gold: dict[tuple[str, str], dict[str, Any]] = {}
    for split in SPLITS:
        for record in _read_jsonl(PACK_ROOT / "data" / split / "expected_results.jsonl"):
            gold[(record["claim_id"], record["rule_id"])] = record
    return gold


def envelope_for(case: Mapping[str, Any]) -> dict[str, Any]:
    """The ORIGINAL claim envelope a case's finding points into."""
    finding = cast("Mapping[str, Any]", case["finding"])
    claim_id = cast("str", finding["claim_id"])
    return load_claims()[claim_id]


class StubModelProvider:
    """A model provider with injected behaviour (no network, no real model).

    ``source_kind`` is ``"model"`` so the layer treats it exactly like a live
    OpenAI-compatible endpoint: whatever it returns must survive the verifier or
    the deterministic text is used instead.
    """

    name = "stub"
    source_kind = "model"

    def __init__(
        self,
        *,
        output: Mapping[str, Any] | None = None,
        error: BaseException | None = None,
        raw_output: bool = False,
    ) -> None:
        self.output = output
        self.error = error
        self.raw_output = raw_output
        self.calls: list[tuple[str, str]] = []
        self.untrusted: list[str | None] = []

    def explain(
        self,
        finding: Mapping[str, Any],
        rule: Mapping[str, Any],
        *,
        untrusted_text: str | None = None,
    ) -> Mapping[str, Any]:
        """Record the call, then raise the injected error or return the output."""
        self.calls.append((str(finding.get("claim_id")), str(finding.get("rule_id"))))
        self.untrusted.append(untrusted_text)
        if self.error is not None:
            raise self.error
        output = self.output
        if output is None:
            raise AssertionError("StubModelProvider needs an output or an error")
        return output

    def compliant_output(
        self,
        finding: Mapping[str, Any],
        *,
        explanation: str = "The submitted unit price is absent, so completeness is unproven.",
    ) -> dict[str, Any]:
        """A contract-clean model output for ``finding`` (citations from the finding)."""
        evidence = finding.get("evidence")
        paths = [
            entry["path"]
            for entry in cast("list[Mapping[str, Any]]", evidence or [])
            if isinstance(entry.get("path"), str)
        ]
        return {
            "explanation": explanation,
            "cited_evidence_paths": paths[:1] or paths,
            "cited_rule_ids": [finding.get("rule_id")],
            "needs_human_review": finding.get("requires_human_review") is True,
        }


def synthetic_finding(**overrides: Any) -> dict[str, Any]:
    """A minimal, contract-shaped finding for pack-independent guard tests."""
    finding: dict[str, Any] = {
        "claim_id": "CG-SYNTHETIC-0001",
        "rule_id": "R013",
        "rule_version": "1.0.0",
        "status": "FAIL",
        "severity": "medium",
        "affected_line_ids": ["L1"],
        "evidence": [
            {"path": "/lines/0/quantity", "value": 1.5},
            {"path": "/lines/0/unit_price", "value": 180},
        ],
        "rule_source": "fictional-rulebook/R013@1.0.0",
        "explanation": "Quantity exceeds fictional maximum",
        "corrective_action": "Verify the billed quantity against the fictional limits.",
        "confidence": None,
        "confidence_kind": "not_probabilistic",
        "requires_human_review": True,
        "method": "deterministic",
        "review_status": "unreviewed",
    }
    finding.update(overrides)
    return finding


#: A minimal envelope matching :func:`synthetic_finding`'s pointers.
SYNTHETIC_ENVELOPE: dict[str, Any] = {
    "claim_id": "CG-SYNTHETIC-0001",
    "lines": [{"line_id": "L1", "quantity": 1.5, "unit_price": 180}],
}

SYNTHETIC_RULE: dict[str, Any] = {
    "rule_id": "R013",
    "title": "Quantity and price limits",
    "severity": "medium",
    "logic": (
        "Every quantity must be a positive integer, unit_price must be greater than zero and at "
        "most policy.max_unit_price[service_code], and quantity must be at most "
        "policy.max_quantity_per_line[service_code]."
    ),
    "corrective_action": "Verify the billed quantity and price against the fictional limits.",
    "version": "1.0.0",
    "source": "fictional-rulebook/R013@1.0.0",
}
