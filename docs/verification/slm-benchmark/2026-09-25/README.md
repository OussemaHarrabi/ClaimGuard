# SLM benchmark artifacts — 2026-09-25

These files are content-preserving copies of the Colab outputs supplied by the team. Repository line
endings are normalized; normalized text comparison against the downloaded files is exact:

- `environment.json` — runtime and model configurations;
- `claimguard_slm_benchmark.csv` — per-case automatic metrics;
- `claimguard_slm_benchmark.json` — aggregate summary, comparisons and raw outputs;
- `claimguard_semantic_review.csv` — human entailment-review template.

The run used a Tesla T4. Five configurations ran; Gemma 4 BF16 was skipped by its memory threshold.
Every `safety_gate_pass` value is false. The semantic-review file has 22 rows and zero completed
`supported` labels, so it is not an adjudicated benchmark. No model is approved for deployment from
this run. See `docs/18-SLM-Benchmark-Methodology.md` §9 for the measured comparison and decision.
