# B2: SLM explanation benchmark

Initial contribution: Maram Kouki. Team Claimix.

Maram's contribution is retained and credited: a focused Gemma 4/Phi-4 Mini/Qwen3 comparison,
a frozen seven-case exploratory corpus, paired NF4 experiments, abstention and direct/base64
injection tests, and a safety-first interpretation.

The **active** benchmark is now [the canonical Colab notebook](../../notebooks/slm_explanation_benchmark_colab.ipynb),
with [the full protocol and rubric](../../docs/26-Production-SLM-Benchmark.md).
There is only one maintained model-generation/evaluation implementation. It calls the real
R001–R015 engine, RFC 6901 evidence verifier, production prompts and actual assistant graph.
It adds SmolLM3 3B, Liquid LFM2.5 1.2B Instruct and Qwen3.5 4B as challengers.

## Contents

- `cases.py`, `test_cases.py`: preserved seven-case exploratory contribution, not production gold labels.
- `archive/slm_explanation_benchmark_colab_v2.ipynb`: original B2 notebook, retained for provenance,
  not the recommended executable protocol.
- `archive/RESULTS-original.md`: original contributor-reported interpretation. Raw run artifacts
  were not included in the PR, so these numbers have not been independently reproduced.
- `RESULTS.md`: current evidence status, not an invented new GPU table.

## Run

From the repository root, in the project's dev environment:

```bash
python -m pytest tests/benchmark team/b2-slm-benchmark/test_cases.py -q
python -m notebooks.slm_benchmark_runner prepare --limit 30 --output artifacts/slm/smoke
python -m notebooks.slm_benchmark_runner report --output artifacts/slm/smoke
```

For GPU work, use Colab and `notebooks/requirements-slm.txt`. No nonexistent root
`requirements.txt` is required. Keep secrets and generated weights outside Git.
T4 does not support native BF16; use the explicitly named FP16 reference or a larger GPU.
No SLM is selected from incomplete human reviews or an unmatched quantization reference.
