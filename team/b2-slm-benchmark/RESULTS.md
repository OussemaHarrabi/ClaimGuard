# B2: current evidence status

Maram Kouki's [original report](archive/RESULTS-original.md) is preserved as contributor-reported
exploratory evidence. The PR did not include the corresponding raw outputs, hardware manifest
or completed semantic reviews, so its percentages and hardware claims have not been reproduced.
In particular, a prohibited-language percentage is not proof of entailment, and missing human
labels must be reported as unknown, not as a 100% unsupported-claim rate.

## What is now integrated

- Real-engine synthetic corpus: 42 families, all 15 rules, 1,890 findings with three variants.
- Family-held-out screening/release split: 1,080 / 810 findings.
- Real provider/parser/verifier/fallback and actual scope/gather/verify/repair assistant graph.
- Output-bound two-reviewer semantic evaluation, with incomplete/disputed labels left unknown.
- Explicit unsupported/OOM configurations, resumable case outputs and frozen model revisions.
- Separate raw drafts and served answers, refusal/repair/fallback traces, timing and VRAM.
- Paired family-clustered NF4 quality analysis that refuses incomplete/unmatched comparisons.
- Three additional challengers, with official model-card references in the protocol.

## What remains unmeasured

The new six-candidate protocol still needs actual Colab GPU execution, two independent semantic
reviews, follow-up question review and finalist held-out confirmation. CPU tests validate the
harness and application contracts, not model generation quality or accelerator compatibility.
No new winner, hallucination-free model or lossless quantization result is claimed.
Application defaults and production permissions are unchanged.

Use [the canonical notebook](../../notebooks/slm_explanation_benchmark_colab.ipynb)
and [the selection protocol](../../docs/26-Production-SLM-Benchmark.md).
