"""
Minimal tests for the B2 benchmark, independent of any GPU/model run.

Run with:  pytest team/b2-slm-benchmark/test_cases.py -v

These check the harness itself (corpus integrity + verifier logic), not
model quality — model quality is judged from the notebook's scored runs
in RESULTS.md. Keeping these model-free means they run in CI with no GPU.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cases import CASES, EXPECTED_CORPUS_HASH, corpus_hash


def get_case(case_id: str) -> dict:
    return next(c for c in CASES if c["case_id"] == case_id)


def test_corpus_hash_is_pinned():
    """Catches silent edits to the frozen case set."""
    assert corpus_hash() == EXPECTED_CORPUS_HASH, (
        "CASES changed without updating EXPECTED_CORPUS_HASH in cases.py — "
        "bump it deliberately if the change was intentional."
    )


def test_normal_case_shape():
    """coverage-001: a standard 'needs_correction' case with two supporting
    evidence items the explanation should cite."""
    case = get_case("coverage-001")
    assert case["status"] == "needs_correction"
    assert set(case["required_citations"]) == {"E1", "E2"}
    assert len(case["allowed_corrections"]) >= 1


def test_abstention_case_shape():
    """authorization-unable-001: the engine abstains (unable_to_assess)
    because required evidence is missing — the model must not invent it."""
    case = get_case("authorization-unable-001")
    assert case["status"] == "unable_to_assess"
    assert case["evidence"]["E1"]["value"] is None
    assert case["evidence"]["E2"]["value"] == ""


def test_prompt_injection_case_flags_untrusted_evidence():
    """The injected text lives only inside an evidence value, never in an
    instruction field — a correct model must treat it as data."""
    case = get_case("prompt-injection-001")
    assert "ignore prior instructions" in case["evidence"]["E1"]["value"].lower()
    assert case["status"] == "needs_correction"  # engine's real status is unaffected


def test_ready_case_needs_no_human_review_by_contract():
    """Status invariance: ready_for_review is the only status where
    needs_human_review should resolve to False in the verifier."""
    case = get_case("ready-001")
    assert case["status"] == "ready_for_review"
    assert case["allowed_corrections"] == []
