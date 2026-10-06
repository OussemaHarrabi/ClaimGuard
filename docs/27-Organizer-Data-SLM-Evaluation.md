# Organizer-data SLM evaluation

The October evaluation uses the **delivered synthetic organizer dataset**, not real
patient records. It is separate from the earlier one-case GPU loader probe. That
probe checks whether a checkpoint runs, and must never decide the winner.

## Data and leakage boundaries

The starter pack contains 400 development, 150 validation and 50 stress claims.
Each claim produces 15 actual ClaimGuard engine findings. The adapter requires
exact gold pair coverage and checks status, severity, version, review flags and
confidence metadata. Both gold and engine evidence must resolve to the original
claim values. Valid engine evidence need not be the same pointer subset as gold.
The gold explanation is **not** passed to a model or used as a generated target.

The starter pack remains private local reference material. Upload its synthetic
claims and expected results to your own Colab runtime, never to the repository.
No patient records, credentials or tokens belong in this evaluation.

Development is for prompt iteration or future training. Validation is for the
initial six-model comparison. Stress is reserved for the selected finalists.
Do not train on validation/stress outputs and then call those splits held out.

## Comparable, substantive experiments

Use every available rule/status stratum, rather than the first N findings.
`--per-stratum 2` yields 92 validation findings with the delivered pack. Selection
is deterministic and content-addressed. Larger runs can increase this parameter;
zero uses all findings. Rare combinations are retained, never invented.
These remain fictional, correlated teaching cases, not independent clinical data.

```bash
python -m notebooks.slm_benchmark_runner run \
  --starter-pack /content/starter-pack \
  --starter-split validation --split release --per-stratum 2 \
  --models gemma4-e4b phi4-mini qwen3-4b smollm3-3b lfm25-12b qwen35-4b \
  --precisions nf4 --output /content/claimix-benchmark/organizer-validation
```

Then evaluate finalists on stress, with conversation checks:

```bash
python -m notebooks.slm_benchmark_runner run \
  --starter-pack /content/starter-pack \
  --starter-split stress --split release --per-stratum 4 \
  --models FINALIST --precisions nf4 fp16 \
  --followups --followup-families 12 \
  --output /content/claimix-benchmark/organizer-stress
```

Replace FINALIST with an actual candidate key. T4 needs FP16, not emulated BF16.
Use matching source commits, model revisions, cases and decoding for precision
comparisons. An OOM is an explicit unsupported configuration, not a quality score.
The conversation budget is recorded in the immutable manifest. Report its actual
coverage; a capped conversation run does not imply exhaustive use-case testing.

Also run the synthetic adversarial corpus for missing values, contradictions,
duplicate lines, rule boundaries, prompt injection and long untrusted text.
All runs preserve raw draft, parsed candidate, served answer, verifier rejections,
fallbacks, latency, token truncation and GPU memory. A safe fallback does not count
as a successful model explanation.

## Decision versus deployment approval

The research deliverable must recommend **one model to continue with** and say
whether targeted fine-tuning is needed. Rank actual verified raw-draft success,
correction usefulness, refusal behavior, precision regressions, memory and latency.
Inspect failed and accepted drafts against their exact rule/evidence. State which
semantic assessments came from an AI analyst versus independent human reviewers.
Do not invent human review labels or certify zero hallucinations from a JSON check.

The existing two-human-review deployment gates remain unchanged. A model may be
the justified research winner without being cleared for unsupervised deployment.
If failures concentrate on task format, source-grounded correction wording or
uncertainty, recommend fine-tuning that winner on development-only synthetic
examples. If prompting and guarded verification already meet the measured goals,
avoid fine-tuning merely to add complexity. Never train the SLM to decide payment,
change rule results, write claims autonomously or access another tenant.

Raw results and the final recommendation will be recorded after GPU execution,
not prefilled with expected results.
