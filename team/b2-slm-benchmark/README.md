# B2 — SLM explanation benchmark

## Question
Which small, locally deployable model — **Gemma 4 E4B**, **Phi-4 Mini**, or **Qwen3 4B** (each in BF16 and 4-bit/NF4) — can turn one ClaimGuard deterministic finding + its evidence into a grounded, five-field explanation (`explanation`, `correction_recommendation`, `cited_evidence_paths`, `cited_rule_ids`, `needs_human_review`), without changing the engine's decision or inventing facts? And does 4-bit quantization preserve quality within each family?

The deterministic engine always owns `rule_id` and `status`. A model may only draft text for a human reviewer — it never approves, denies, submits or mutates a claim.

## Setup
```bash
pip install -r requirements.txt   # transformers, accelerate, bitsandbytes, pandas, sentencepiece, huggingface_hub
```
- Needs a CUDA GPU (tested on a Tesla T4, 14.6 GB) to load the models.
- Gemma 4 E4B is gated — accept the license on its Hugging Face model page and run `huggingface_hub.notebook_login()` once.
- No real claim data is used anywhere; `cases.py` is 100% synthetic.

## One-command demo
```bash
pytest team/b2-slm-benchmark/test_cases.py -v
```
This runs model-free (no GPU needed) — it checks the frozen test corpus and verifier logic only. **Expected output:** 5 tests pass, confirming the corpus hash `4f85e01314a84214` and the shape of the normal / abstention / prompt-injection cases.

To run the full model benchmark (GPU required): open `slm_explanation_benchmark_colab_v2.ipynb` in Colab or Kaggle with a GPU runtime and Internet enabled, then **Run All**. Expected output: a per-config results table, a BF16-vs-NF4 comparison, and `claimguard_slm_benchmark.csv/json` + `recommendation.md` written to `team/b2-slm-benchmark/`.

## Files
- `cases.py` — the frozen, hashed synthetic test corpus (7 cases).
- `test_cases.py` — model-free tests: 1 normal case (`coverage-001`), 1 abstention case (`authorization-unable-001`), plus prompt-injection and status-invariance checks.
- `slm_explanation_benchmark_colab_v2.ipynb` — the executable benchmark (loads each model, scores outputs, exports artifacts).
- `RESULTS.md` — baseline, measured comparison, environment, and example errors.

## Five-minute demo
See **"Demo walkthrough"** in `RESULTS.md`.
