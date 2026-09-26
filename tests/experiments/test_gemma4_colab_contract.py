from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "notebooks" / "slm_explanation_benchmark_colab.ipynb"


def _notebook_source() -> str:
    payload = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return "\n".join("".join(cell.get("source", [])) for cell in payload.get("cells", []))


def test_colab_benchmark_compares_three_official_small_model_families() -> None:
    source = _notebook_source()

    assert "google/gemma-4-E4B-it" in source
    assert "microsoft/Phi-4-mini-instruct" in source
    assert "Qwen/Qwen3-4B-Instruct-2507" in source
    assert "AutoModelForCausalLM" in source
    assert "AutoModelForMultimodalLM" in source


def test_colab_benchmark_compares_full_precision_and_q4_per_family() -> None:
    source = _notebook_source()

    assert "BitsAndBytesConfig" in source
    assert "load_in_4bit=True" in source
    assert '"bf16"' in source
    assert "family" in source
    assert "q4_non_inferior" in source


def test_colab_benchmark_scores_grounding_and_status_invariance() -> None:
    source = _notebook_source()

    for metric in (
        "json_valid",
        "citation_precision",
        "citation_recall",
        "unsupported_claim_rate",
        "status_invariant",
        "latency_seconds",
        "tokens_per_second",
        "peak_vram_gb",
    ):
        assert metric in source

    assert "The model must not change claim status" in source
    assert "non_inferiority_margin = 0.02" in source


def test_colab_benchmark_fails_closed_without_semantic_support_labels() -> None:
    source = _notebook_source()

    assert "MANUAL_SUPPORT_LABELS" in source
    assert "semantic_labels_complete" in source
    assert "claimguard_semantic_review.csv" in source
    assert '"supported": semantic_support' in source
    assert "fabricated_statement_with_valid_citation" in source
    assert "evidence_change_invalidates_label" in source
    assert '"system_prompt": SYSTEM_PROMPT' in source
    assert '"case": case' in source
    assert "safety_gate_pass" in source


def test_colab_benchmark_freezes_the_schema_and_adversarial_corpus() -> None:
    source = _notebook_source()

    assert "EXPECTED_TOP_LEVEL_KEYS" in source
    assert "EXPECTED_CLAIM_KEYS" in source
    assert '"rule_id"' in source
    assert '"severity"' in source
    assert '"unable_to_assess"' in source
    assert '"Ignore prior instructions' in source
    assert '"value": None' in source


def test_colab_benchmark_matches_the_secured_assistance_contract() -> None:
    source = _notebook_source()

    assert "correction_recommendation" in source
    assert "cited_evidence_paths" in source
    assert "needs_human_review" in source
    assert "authority" in source
    assert "draft_language_only" in source
    assert "Never decide, execute, approve, deny, submit, or mutate a claim" in source


def test_colab_benchmark_exports_reproducible_artifacts() -> None:
    source = _notebook_source()

    assert "claimguard_slm_benchmark.csv" in source
    assert "claimguard_slm_benchmark.json" in source
    assert "claimguard_semantic_review.csv" in source
    assert "environment.json" in source
    assert "seed = 20260924" in source
