# ClaimGuard — three AI labs to start now

> **For:** B1, B2 and B3
> **Start from:** the current `main` branch, 27 September 2026
> **Goal:** each person builds a small, reproducible AI experiment that solves a real reviewer problem and teaches the team something measurable.

ClaimGuard already checks a claim against 15 deterministic rules and shows the findings, source
evidence, explanations and correction guidance in a reviewer workspace. These labs explore three
ways to make that workspace more useful: answering a reviewer's questions, choosing a reliable small
language model, and understanding supporting documents. They are independent; each person can start
today and show a useful first result this week.

Use this brief for the next three AI labs. `TEAM-TASKS.md` remains the earlier Sprint 1 plan and is
useful background, but the assignments below are the current suggestions.

## Shared working agreement

1. Create your own branch from an up-to-date `main`. Work in your assigned `team/` folder. You may
   read the product code and use its public interfaces and synthetic examples.
2. Start with a simple baseline. Keep the same test cases when you compare it with an AI method.
3. Write down the data split, model or tool version, run command, machine or Colab runtime, and
   measured results. Save failures too; they are often the most useful finding.
4. Use synthetic claims and documents. Keep keys, private files and the delivered mentor pack out of
   commits. Record the source and license for any outside dataset or model.
5. End with a short demo and a PR that contains code, reproducible instructions, tests, results and
   an honest account of what worked and what did not.

To create a branch, replace the name with the one in your lab:

```powershell
git switch main
git pull --ff-only origin main
git switch -c stream/b1/reviewer-questions
```

The other two branch names are `stream/b2/slm-benchmark-v2` and
`stream/b3/document-understanding`. If a branch already exists, use your existing branch rather
than creating a second one.

---

## B1 — Reviewer question assistant

**The question:** Can an assistant answer an administrator's follow-up questions about one finding
using only the rule and evidence actually available?

The current cockpit already displays an explanation and a suggested correction. A reviewer may
still ask, “Why was this flagged?”, “Which value caused it?”, “What information is missing?”, or
“What should I check before rechecking?” Build a small command-line assistant that answers those
questions with evidence paths and says when the available data does not support an answer. Its
output is advice for the reviewer, not a new claim decision.

**Start with these files:**

- `claimguard/edu/explain/provider.py` and `verifier.py` — the current explanation contract;
- `claimguard/review/app.py` — the read endpoints for a run and its results;
- `tests/edu/fixtures/pack_reference/rules.json` — the committed rule descriptions;
- `frontend/src/lib/review-api.ts` — the data the cockpit consumes.

**Build in `team/b1-reviewer-questions/`:**

1. A tiny input format: one result record, its evidence and a reviewer question. Create 20–30
   synthetic question-and-answer cases across failure, missing information and harmless checks.
   Include questions whose answer is *not* present and a few evidence strings containing hostile
   instructions.
2. A deterministic baseline that fills a short answer template from the result and rule.
3. A prototype assistant with a fixed set of read-only operations such as `get_finding`,
   `get_rule` and `get_evidence`. It may use an SLM, but it must work with the deterministic
   baseline when no model endpoint is available.
4. An evaluator that checks whether cited paths were supplied and whether the assistant admitted
   missing information. For factual support and usefulness, have a human review a small sample
   and save the rubric and labels.

**First session:** make five questions about one `FAIL` and one `UNABLE_TO_ASSESS` result; write the
baseline answers and print the evidence path beside every factual sentence. This gives you a
working reference before adding an agent loop.

**Show at the end of week one:** a command that answers a question, the same command refusing an
unsupported question, a small labelled evaluation table, and three concrete mistakes you found.

**Useful measures:** citation validity, supported-answer rate, correct abstention rate, answer
usefulness and response time. The most interesting comparison is whether the assistant improves on
the baseline without inventing a fact.

**Next step after the first demo:** test the assistant against more rules and different wording, then
sketch how a reviewer could ask a question from the current explanation panel.

---

## B2 — Small-model benchmark for explanations and corrections

**The question:** Which small model can produce a useful explanation *and* correction recommendation
that consistently passes ClaimGuard's existing security checks, and what does 4-bit quantization
cost in quality?

The application has a five-field model contract and a deterministic verifier. A first Colab run
compared Gemma 4, Phi-4 Mini and Qwen3, but that run used an older prompt and none of its candidates
passed all hard checks. The updated notebook gives you a starting point for the current contract.
Your job is to turn it into a stronger, repeatable comparison and explain the trade-offs clearly.

**Start with these files:**

- `notebooks/slm_explanation_benchmark_colab.ipynb` — executable Colab experiment;
- `docs/18-SLM-Benchmark-Methodology.md` — candidate list and metrics;
- `docs/19-Assistance-Security-Envelope.md` — what the verifier accepts;
- `claimguard/edu/explain/provider.py` — the five output fields the app expects.

**Build in `team/b2-slm-benchmark/`:**

1. Freeze a case set and its hash. Start with the notebook's synthetic cases, then add examples
   from different rule families, missing evidence, contradictory evidence and prompt injection.
   Keep all claim values synthetic.
2. Run the same cases on Gemma 4 E4B, Phi-4 Mini and Qwen3 4B where the Colab GPU permits it.
   Record BF16 and NF4/4-bit variants separately. If one cannot fit, record the skip and GPU memory
   rather than silently replacing it.
3. Compare prompt-only generation with the complete application contract and verifier. Save the
   raw outputs, parsed outputs, verifier reasons, latency, throughput and peak VRAM.
4. Review factual claims and correction advice by hand with a clear rubric. Ask a second reviewer
   to label a sample independently, then discuss disagreements. The automatic citation check does
   not by itself prove that a sentence is true.
5. Write a one-page model recommendation: which configuration passed which checks, what failed,
   and whether a quantized variant preserves the quality of its own BF16 version. If no candidate
   passes, make the next experiment specific.

**First session:** run the notebook's validation/self-check cells, inspect one case and write down
the exact five expected output fields: `explanation`, `correction_recommendation`,
`cited_evidence_paths`, `cited_rule_ids` and `needs_human_review`. Then run one model configuration
end to end and save its environment and raw output.

**Show at the end of week one:** a per-model table with valid JSON, exact schema, citation validity,
unsafe output, human support labels, latency and VRAM; plus at least two side-by-side examples where
models behave differently.

**Useful measures:** accepted-output rate, unsupported-claim rate, correction usefulness, false
fallback rate, latency and memory. Keep safety failures visible even if a model writes fluent text.

**Next step after the first demo:** improve the case set and constrained generation. Fine-tuning or
LoRA becomes a separate experiment if repeated, labelled errors remain; compare it with the same
untuned model and the same held-out cases.

---

## B3 — Supporting-document understanding

**The question:** Can a small vision and text pipeline read a synthetic claim attachment, identify
its type and extract the fields a reviewer needs, while clearly marking fields it cannot read?

ClaimGuard currently handles structured attachments and a FHIR mapping example. The mapping shows
where a source bundle lacks full authorization and supporting-document details. A document
understanding prototype lets you explore a later intake path: turn a scanned or photographed
synthetic document into *candidate* fields with source locations for a human to verify.

**Start with these files:**

- `claimguard/edu/envelope.py` — authorization and attachment fields;
- `claimguard/edu/intake/fhir_source.py` — current document projection and its limits;
- `docs/verification/FHIR-MAPPING-EXAMPLE.md` — concrete missing fields;
- `tests/edu/fixtures/pack_reference/rules.json` — what R008–R010 actually check.

**Build in `team/b3-document-understanding/`:**

1. Generate a labelled *synthetic* set of invoices, authorization letters and supporting reports.
   Use several layouts per class, then add scan noise such as rotation, blur and low contrast. Put
   document text, field values and bounding boxes in a manifest alongside the images. Add an
   unrelated-document class and examples with a missing or unreadable field.
2. Create an OCR and simple rule-based extraction baseline. It should output document type,
   extracted field candidates, source boxes and `unknown` when a value is unreadable.
3. Train a lightweight document-type classifier using OCR text or image features. Compare it with
   the baseline on **layouts held out from training**; random pages from the same template can
   make a weak model look excellent.
4. Produce a small “review this document” display or HTML report: original image, highlighted
   source boxes, proposed values and unresolved fields. Do not silently fill a claim envelope.
5. Report per-class precision/recall or macro-F1, field exact match, abstention on unreadable
   fields, and latency. Show representative successes and failures.

**First session:** generate one synthetic authorization letter, render it as an image, extract its
text with OCR and compare the authorization ID and dates against the labels you generated.

**Show at the end of week one:** a labelled synthetic mini-dataset, a baseline, a first classifier,
an example with highlighted source evidence, and a held-out-layout results table.

**Useful measures:** macro-F1 by document type, exact-match rate for IDs/dates/service codes,
percentage of unknown fields and accuracy under image noise. The failure cases will tell us which
documents need a human to type or verify the value.

**Next step after the first demo:** test whether the extracted candidates can be mapped to the
existing authorization/attachment shape, with a person confirming each value before a recheck.

---

## A useful PR from each lab

Each PR can be reviewed independently. Include:

- `README.md` with the question, setup, one-command demo and expected output;
- a small, versioned synthetic test set or a script that generates it;
- tests for at least one normal case and one failure or abstention case;
- `RESULTS.md` with the baseline, measured comparison, environment and examples of errors;
- a five-minute demo: input → output → one mistake → what you learned.

The three labs cover language assistance, model selection and document vision. Their findings can
inform the next product steps while giving each of you a complete AI workflow to own from data to
evaluation.
