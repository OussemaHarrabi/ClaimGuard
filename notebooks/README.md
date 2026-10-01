# Colab experiments

This directory contains the reproducible small-language-model experiment for ClaimGuard's explanation and correction-guidance layer.

[Back to the project README](../README.md)

## Notebook

Open `slm_explanation_benchmark_colab.ipynb` in Google Colab. It compares:

- `google/gemma-4-E4B-it`
- `microsoft/Phi-4-mini-instruct`
- `Qwen/Qwen3-4B-Instruct-2507`

The notebook attempts BF16 and 4-bit NF4 variants when the assigned GPU has enough memory. Gemma weights may require accepting Google's license and authenticating to Hugging Face.

## Evaluation contract

Each case starts with a status and evidence already produced by the deterministic engine. A candidate may explain the finding and suggest a bounded correction, but may not change the status, invent evidence, adjudicate, or execute the correction.

Selection is safety-first:

1. preserve the deterministic status;
2. follow the exact output schema;
3. cite only allowed evidence;
4. introduce no unsupported claims or instruction-following from untrusted claim text;
5. pass human entailment and correction-usefulness review;
6. only then compare latency, memory, and quantization non-inferiority.

## Current result

The preserved T4 run evaluated five configurations. Gemma 4 BF16 did not fit the declared memory threshold. Every executed configuration failed at least one hard safety gate, and the semantic-review sheet has no completed human support labels. Therefore **no SLM is selected for deployment**. Qwen3 4B BF16 had the highest raw aggregate score, but unsafe prompt-payload repetition and schema failures disqualify it. Gemma 4 E4B Q4 is the next experimental candidate, not a winner.

ClaimGuard consequently uses deterministic explanations unless an operator explicitly configures a model, and every model draft still passes through the verifier and fallback path.

Read [the complete methodology and measured table](../docs/18-SLM-Benchmark-Methodology.md) and [the preserved output manifest](../docs/verification/slm-benchmark/2026-09-25/README.md).

## Running responsibly

- Use only synthetic, de-identified benchmark cases.
- Record the accelerator, package versions, model revision, precision, seed, and runtime configuration.
- Export both automatic results and the semantic-review template.
- Have two reviewers label entailment and resolve disagreement before declaring a gate passed.
- Do not call a quantized model equivalent to BF16 without the declared non-inferiority comparison.
- Do not copy Hugging Face tokens or downloaded weights into the repository.
