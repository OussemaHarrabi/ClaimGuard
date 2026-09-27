# Team task sheets — Sprint 1 (earlier lab plan)

> **Current AI labs:** [`TEAM-AI-LABS-2026-09-27.md`](TEAM-AI-LABS-2026-09-27.md) has the next
> assignments for B1, B2 and B3. The plan below is retained as background and reference.

> **Who this is for:** B1, B2 and B3.
> **Read this with:** `TEAM-ROADMAP.md` (how we work) and `docs/01-Domain-Gulf-Claims-101.md`
> (the domain, if you have not read it yet).

---

## How this document works

Each of you gets **one lab**: a self-contained piece of AI work in your own field that
produces something real we can show the mentor and the jury.

**These three labs are independent by construction.** You do not share files, you do not
depend on each other's output, and no lab can break the product:

- you **write only** inside your own folder — B1 → `team/b1-grounding/`,
  B2 → `team/b2-risk-model/`, B3 → `team/b3-retrieval/`;
- you **read anything** — the engine, the data, the docs. Reading is how you learn what a
  real codebase looks like;
- the product code (`claimguard/**`) is **read-only** for you. Nothing you do can change
  what the jury sees, and nothing the rest of us do can break your lab;
- **one branch per lab:** `stream/<your-id>/<topic>` (e.g. `stream/b2/risk-model`), then a PR.

Two rules that matter more than speed:

1. **Never write a number you did not measure.** If you did not run it, do not state it.
2. **Never let a label leak.** When you train or score anything, the rule is: fit on
   **development**, evaluate on **validation**. The mentor's 200 held-out claims are not in
   this repository — never pretend otherwise.

### The environment (do this once)

```bash
uv sync --all-extras        # installs everything, including scikit-learn and numpy
uv run pytest tests/ -q     # should pass; some tests skip without a database, that is fine
```

The mentor's data ("the pack") is at
`ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack`. It is **not stored in
git** (delivered reference material), so:

> **CI rule.** Any test of yours that needs the pack must skip cleanly when it is absent, or
> our pipeline goes red. Copy the pattern in
> `tests/edu_conformance/test_harness_selfcheck.py`:
> `pytest.mark.skipif(not PACK.is_file(), reason="mentor starter pack absent ...")`.

### What already exists (build on it, do not rebuild it)

| Piece | Path | What it gives you |
|---|---|---|
| Engine (15 rules) | `claimguard/edu/` | `evaluate_claim(claim, ctx)` → 15 result records |
| Result records | — | 15 keys: `claim_id, rule_id, rule_version, status, severity, affected_line_ids, evidence, rule_source, explanation, corrective_action, confidence, confidence_kind, requires_human_review, method, review_status` |
| Rule catalogue (committed) | `tests/edu/fixtures/pack_reference/` | `rules.json`, `policies.json`, `services.json` — works without the pack |
| Explanation layer | `claimguard/edu/explain/` | deterministic + model-assisted explanations, citation checks |
| Measured results | `docs/verification/EDU-EVALUATION-REPORT.md` | the numbers to compare against |

Produce records for yourself in one command:

```bash
uv run python -m claimguard.edu.run \
  --claims ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/data/development/claims.jsonl \
  --rules-dir ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/rules \
  --output C:/tmp/dev_results.jsonl
```

---

# B1 — The grounding and handover lab (your field: AI / language / agents)

**Your mission.** Two things nobody has built: a **machine check that an explanation is
actually grounded** in the evidence it cites, and a **bounded agent** that turns one finding
into a reviewer handover using tools rather than guesswork.

**Why it matters.** The mentor gives 20 of 100 points to grounded AI explanations and says
plainly that explanation quality is *not* scored by any script — so today we cannot prove our
explanations are honest, only that they are non-empty. And the pack asks for exactly this:
*"Let the assistant select supplied rules, call read-only evidence tools, explain findings and
request human review. Allow only named tools with typed inputs."* Your lab is that.

**Read first (30 minutes):**
- `claimguard/edu/explain/` — how explanations are produced today, and what a citation is.
- `claimguard/edu/emit.py` — how evidence is built (`{path, value}` into the original claim).
- The pack: `docs/05_Architecture_and_AI.md` ("AI exercise" and "Agent behaviour to
  demonstrate") and `prompts/explain_findings.md`.
- The pack's 25 explanation cases: `exercises/llm_explanation_cases.jsonl`.

**Build, in this order:**

| Step | Deliverable in `team/b1-grounding/` |
|---|---|
| 1 | `citation_check.py` — split an explanation into sentences and check each one against the finding's cited evidence: does every claim trace to a pointer, and does any sentence assert something the evidence cannot support (a decision, a clinical judgement, an invented value)? Report per-sentence verdicts and a per-finding score. |
| 2 | `handover_agent.py` — a small bounded agent with a **fixed tool list**, each tool typed and read-only: `get_finding(claim_id, rule_id)`, `get_evidence(claim_id, rule_id)`, `get_rule(rule_id)`, `request_human_review(claim_id, rule_id, why)`. It runs the loop: read the finding → fetch the rule → fetch the evidence → produce a structured handover. No tool may write to the ledger and no tool may change a status. |
| 3 | `scorecard.py` + `filled_scorecard.csv` — hand-score the pack's 25 cases on five 0/1 criteria (correct finding / correct evidence / correct rule / appropriate action / honest uncertainty) and compute the totals. This is the human baseline your automated checker is measured against. |
| 4 | `FINDINGS.md` — does the automated checker agree with your human scores? Where does it over- or under-flag? What would you change? |

**How you know you are done:**
- [ ] All 25 cases appear in the scorecard and you scored every one by hand.
- [ ] `citation_check.py` runs over a real results file and prints per-sentence verdicts.
- [ ] The agent runs end-to-end with **no network and no API key** (tools are local; the
      "model" step can be a deterministic policy you write).
- [ ] `uv run pytest team/b1-grounding -q` passes, including a test that an ungrounded
      sentence (one citing nothing) is caught.
- [ ] Every number in `FINDINGS.md` comes from your own output.

**If you get stuck:** the hard part is sentence splitting and deciding what "supported" means.
Start naive (split on `.`), get the pipeline running end to end, then improve. A working
naive checker beats a perfect unwritten one.

---

# B2 — The risk model lab (your field: deep learning)

**Your mission.** Train a model that predicts, from the **claim alone**, whether a claim will
have at least one failing check — a fast triage model for the queue — and evaluate it honestly.

**Why it matters.** Today the queue is ordered by nothing. A model that says "this claim
probably has a problem" lets a reviewer look at the risky claims first. It is also the first
machine-learning component in the project, so it must demonstrate the discipline that makes
ML trustworthy: a real split, no leakage, honest metrics, and calibration.

**Read first (30 minutes):**
- The pack's `docs/07_Evaluation_and_Acceptance.md` — the metric philosophy.
- `ClaimGuardAI_Student_Starter_Pack/.../data/dataset_manifest.json` — the declared counts and
  the public/per-split labels.
- `docs/verification/EDU-EVALUATION-REPORT.md` — our measured engine results, your baseline.
- `claimguard/edu/envelope.py` — the exact 17-key claim shape you will featurise.

**Build, in this order:**

| Step | Deliverable in `team/b2-risk-model/` |
|---|---|
| 1 | `build_dataset.py` — turn the development and validation splits into a feature table: one row per claim, features from the envelope only (counts, nulls, dates as day offsets, amounts, code presence, provider/policy membership), and the label "has at least one FAIL among the 15 checks". Print the class balance. |
| 2 | `baseline.py` — the honest baselines first: majority class, and a single-feature rule. A model that cannot beat these is not a result. |
| 3 | `model.py` — train at least two models: a logistic regression (interpretable) and a small neural network (`sklearn.neural_network.MLPClassifier`). **Fit on development, evaluate on validation.** Report precision, recall, F1, ROC-AUC, and the confusion matrix. |
| 4 | `calibration.py` — plot/print a reliability table: when the model says 0.8, is it right about 80% of the time? Report Brier score and a calibration curve. This is the part that separates a demo from a model. |
| 5 | `FINDINGS.md` — what the model can and cannot do, which features matter, where it fails, and why it must **never** replace the rules (it predicts a probability; the rules produce the verdicts the jury grades). |

**The discipline that earns the marks:**
- **Never** train and test on rows from the same claim or split — say in your report exactly
  which split you fitted on and which you evaluated on.
- **Never** touch the mentor's held-out set (it is not here — do not invent numbers for it).
- Compare against the deterministic engine: the engine is the reference, your model is a
  triage aid. Say so.

**How you know you are done:**
- [ ] The label is derived by actually running the engine (`python -m claimguard.edu.run`), not
      by copying `expected_results.jsonl` — or if you do use the gold file, say so and explain
      why it is equivalent.
- [ ] Metrics reported on the **validation** split, with the class balance shown.
- [ ] A calibration table with real numbers.
- [ ] `uv run pytest team/b2-risk-model -q` passes, including a test that your feature builder
      never reads a field that only exists *after* the rules run (that would be leakage).
- [ ] `FINDINGS.md` states plainly what the model is **not** allowed to be used for.

**If you get stuck:** the most common failure here is leakage — a feature like "number of
findings" that only exists because the rules already ran. If your model scores 0.99, suspect
leakage before celebrating.

---

# B3 — The retrieval quality lab (your field: AI / information retrieval)

**Your mission.** Build a search index over the rulebook and policy documents, then **measure
how good it is**. When a reviewer asks "which rule explains this?", retrieval quality decides
whether the right text ever reaches them — and nobody has measured ours, because we have none.

**Why it matters.** Every credible explanation system sits on retrieval: find the right rule
excerpt, the right policy clause, the right worked example. The mentor's own architecture asks
the assistant to *"select supplied rules"*. Retrieval quality is measurable, it is pure AI
work, and it needs no API key — which is why it is the perfect lab for a CV person moving into
AI engineering.

**Read first (30 minutes):**
- `ClaimGuardAI_Student_Starter_Pack/.../rules/rules.json` and `policies.json` — the corpus.
- The committed copy at `tests/edu/fixtures/pack_reference/` — same files, always available.
- The pack's `docs/04_Rulebook.md` and `docs/03_Data_Dictionary.md` — the prose corpus.
- `docs/verification/EDU-EVALUATION-REPORT.md` — the findings you will build queries from.

**Build, in this order:**

| Step | Deliverable in `team/b3-retrieval/` |
|---|---|
| 1 | `corpus.py` — load and chunk the corpus into retrievable passages (one rule = one passage; split long prose sensibly). Print the corpus size and a few examples. |
| 2 | `bm25.py` — implement BM25 **yourself** (term frequencies, document frequencies, the k1 and b parameters, length normalisation). No search library. Explain each formula in a comment. |
| 3 | `queries.jsonl` — build a labelled query set: for a finding (its evidence and symptom), which rule passage is relevant? At least 40 queries with relevance judgements, derived from real claims, written **by you** — this is the ground truth your metrics stand on. |
| 4 | `evaluate_retrieval.py` — report **recall@1, recall@5, MRR and nDCG@5**, plus a failure analysis of the queries that failed. Compare BM25 against a naïve keyword baseline. |
| 5 | `FINDINGS.md` — how good is lexical retrieval on our corpus, which queries fail and why (vocabulary mismatch, abbreviations, synonyms), and what an embedding-based retriever would fix that BM25 cannot. |

**How you know you are done:**
- [ ] BM25 is your own implementation; you can explain k1 and b to the team in one sentence each.
- [ ] The query set is real and labelled, with the reasoning recorded for at least a few cases.
- [ ] Metrics are reported with the number of queries, and the naive baseline is shown beside
      them so the improvement is visible.
- [ ] The failure analysis names concrete queries, not generalities.
- [ ] `uv run pytest team/b3-retrieval -q` passes, including a test on a tiny hand-built corpus
      where you know the correct ranking.
- [ ] No claim about embedding quality that you did not measure.

**If you get stuck:** start with 10 queries and a 15-passage corpus — the whole pipeline on a
toy scale — then grow the query set. Retrieval work fails when the evaluation harness is
elaborate and the labels are thin; do it the other way round.

---

# Why these three are independent

| | B1 reads | B2 reads | B3 reads |
|---|---|---|---|
| Own folder only (writes) | `team/b1-grounding/` | `team/b2-risk-model/` | `team/b3-retrieval/` |
| Product code | read-only | read-only | read-only |
| Engine output | yes | yes | yes |
| Rule catalogue | yes | yes | yes |
| Other teammates' output | **no** | **no** | **no** |

No lab consumes another's artifacts, so nobody waits and nobody blocks. If you finish early,
add a second metric or a harder case — do not reach into someone else's folder.

---

# The week

| When | B1 | B2 | B3 |
|---|---|---|---|
| Day 1 | Read the explain layer, run the engine, open your branch | Read the metric philosophy, start `build_dataset.py` | Read rules.json, build `corpus.py` |
| Day 2 | `citation_check.py` on real results | Baselines + feature builder finished | BM25 implemented, toy test passing |
| Day 3 | Hand-score all 25 cases | Train both models, validation metrics | 40 labelled queries |
| Day 4 | `handover_agent.py` + `FINDINGS.md` | Calibration table + `FINDINGS.md` | Metrics + failure analysis |
| Day 5 | PR + 5-minute demo to the team | PR + 5-minute demo | PR + 5-minute demo |

**Done, for any lab:** it runs from a clean checkout, it has at least one test that would fail
if the logic broke, every number traces to a command, and you can explain it in five minutes
without reading it aloud.

---

# One thing to keep straight

Everything here is **synthetic and educational**. Our system pre-validates administrative data:
it never approves, denies or judges a claim, and it never gives medical advice. If anything in
your lab's output could be read as "this claim should be paid" or "this patient needs X", that
is a defect — tell the project lead rather than writing around it. A model that predicts a
probability is helping a human look in the right place; it is not deciding anything.
