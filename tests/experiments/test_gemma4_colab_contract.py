"""The notebook orchestrates shared production-aligned modules, never a second verifier."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claimguard.benchmark.candidates import CANDIDATES
from claimguard.benchmark.corpus import fingerprint, generate_cases
from claimguard.benchmark.experiment import run_explanation
from claimguard.benchmark.scoring import compare_quantization, score_output
from claimguard.edu.explain.fallback import build_explanation
from claimguard.edu.policy import RuleContext

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "notebooks" / "slm_explanation_benchmark_colab.ipynb"


def _cases() -> list[dict[str, Any]]:
    return generate_cases(
        RuleContext.from_rules_dir(ROOT / "tests/edu/fixtures/pack_reference"), variants=1
    )


def test_colab_benchmark_retains_original_families_and_adds_challengers() -> None:
    assert {spec["model_id"] for spec in CANDIDATES.values()} == {
        "google/gemma-4-E4B-it",
        "microsoft/Phi-4-mini-instruct",
        "Qwen/Qwen3-4B-Instruct-2507",
        "HuggingFaceTB/SmolLM3-3B",
        "LiquidAI/LFM2.5-1.2B-Instruct",
        "Qwen/Qwen3.5-4B",
    }
    payload = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    for cell in payload["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), "colab-cell", "exec")
    source = "\n".join("".join(cell["source"]) for cell in payload["cells"])
    assert "notebooks.slm_benchmark_runner" in source
    assert "RUN_RELEASE = False" in source


def test_precision_protocol_records_unsupported_native_bf16_and_uses_official_loaders() -> None:
    source = (ROOT / "notebooks/slm_benchmark_runner.py").read_text(encoding="utf-8")
    assert "torch.cuda.is_bf16_supported(including_emulation=False)" in source
    assert "BitsAndBytesConfig" in source and 'bnb_4bit_quant_type="nf4"' in source
    assert "trust_remote_code=False" in source and "use_safetensors=True" in source
    assert "AutoModelForCausalLM" in source and "AutoModelForMultimodalLM" in source
    assert compare_quantization([], [])["verdict"] == "not_established"


def test_real_pipeline_preserves_status_and_exports_bad_draft_separately() -> None:
    case = _cases()[0]
    before = fingerprint(case)
    record = run_explanation(case, lambda messages: '{"explanation":"The claim is paid."}')
    assert fingerprint(case) == before
    assert record["status_unchanged"] is True
    assert record["fallback_used"] is True
    assert record["raw_score"]["accepted"] is False
    assert record["served_score"]["accepted"] is True


def test_semantics_are_unknown_until_exact_outputs_receive_independent_reviews() -> None:
    case = _cases()[0]
    output = build_explanation(case["finding"], case["rule"])
    result = score_output(case, output, [])
    assert result["unsupported"] is None and result["semantic_complete"] is False
    # A valid pointer does not prove a fabricated assertion is supported.
    output["explanation"] = "The recorded coverage has a remaining balance of 5000 SAR."
    result = score_output(case, output, [])
    assert result["unsupported"] is None
    assert (
        result["review_key"]
        != score_output(case, build_explanation(case["finding"], case["rule"]), [])["review_key"]
    )


def test_corpus_is_content_addressed_and_uses_real_statuses_and_untrusted_notes() -> None:
    cases = _cases()
    assert fingerprint(cases) == fingerprint(_cases())
    assert {case["finding"]["status"] for case in cases} >= {
        "PASS",
        "FAIL",
        "UNABLE_TO_ASSESS",
        "NOT_APPLICABLE",
    }
    assert any(case["family"] == "encoded-injection" for case in cases)
    assert any("Ignore prior instructions" in case["envelope"]["notes"] for case in cases)
    assert any(case["envelope"]["total_amount"] is None for case in cases)
    assert all(case["finding"]["rule_id"].startswith("R") for case in cases)


def test_production_contract_rejects_extra_authority_and_changed_review_flag() -> None:
    case = _cases()[0]
    output = build_explanation(case["finding"], case["rule"])
    output["status"] = "APPROVED"
    output["needs_human_review"] = not case["finding"]["requires_human_review"]
    assert score_output(case, output, [])["accepted"] is False


def test_shared_runner_exports_resumable_provenance_and_never_auto_selects() -> None:
    source = (ROOT / "notebooks/slm_benchmark_runner.py").read_text(encoding="utf-8")
    for artifact in (
        "manifest.json",
        "cases.json",
        "deterministic-baseline.json",
        "explanations.jsonl",
        "followups.jsonl",
        "runtime.json",
        "semantic-review-template.csv",
        "summary.json",
    ):
        assert artifact in source
    for field in (
        "source_commit",
        "source_files",
        "corpus_hash",
        "packages",
        "seed",
        "revision",
        "peak_allocated_gib",
        "tokens_per_second",
        "truncated",
    ):
        assert field in source
    assert '"winner": None' in source
    assert "CLAIMGUARD_EXPLAIN_MODE" not in source
