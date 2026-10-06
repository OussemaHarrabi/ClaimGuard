# Colab small-model experiments

[Back to ClaimGuard](../README.md)

Open [slm_explanation_benchmark_colab.ipynb](slm_explanation_benchmark_colab.ipynb) in Colab.
The active protocol uses the real ClaimGuard engine, production verifier and reviewer graph,
not a parallel rule simulator. It compares Gemma 4 E4B, Phi-4 Mini, Qwen3 4B Instruct 2507,
SmolLM3 3B, LFM2.5 1.2B Instruct and Qwen3.5 4B.

Read [the full protocol, setup, review rubric and release gates](../docs/26-Production-SLM-Benchmark.md)
before declaring a winner. The notebook defaults to a small screening smoke run. Held-out release
execution is deliberately opt-in. **No candidate is newly selected for deployment.**

`slm_benchmark_runner.py` is the common resumable CLI. Run it as a module from the repository
root: `python -m notebooks.slm_benchmark_runner --help`.
`requirements-slm.txt` contains GPU-only dependency pins; backend dependencies remain locked separately.
Model-free tests live under `tests/benchmark`, so ordinary CI collects them.

Historical September measurements remain under
[docs/verification/slm-benchmark/2026-09-25](../docs/verification/slm-benchmark/2026-09-25/README.md).
Maram Kouki's B2 contribution and original notebook/report are preserved under
[team/b2-slm-benchmark](../team/b2-slm-benchmark/README.md).

Use synthetic data only. Keep tokens, weights, local credentials and private handoffs out of Git.
Capture the exact source/model revisions, package versions, GPU and decoding settings. On T4,
use FP16 as the named unquantized reference, not BF16. Missing labels and missing precision
references are unknown, never passing safety or quality results.
