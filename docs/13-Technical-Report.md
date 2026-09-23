# 13 — Technical report

> **Status:** Phase-1 submission document · written 2026-09-23.
> **Team:** CSTAM-VELODOC · challenge CSTAM 3.0 · mentor pack v1.0.0 (17 Sep 2026).
> **Headline, quoted from our own measured report:** *"6000 claim-rule pairs, status accuracy
> 1.0000, issue precision 1.0000, issue recall 1.0000, false alarms 0, missed issues 0."*
> — `docs/verification/EDU-EVALUATION-REPORT.md`, headline (development split).
> **Everything numeric below is copied from `docs/verification/EDU-EVALUATION-REPORT.md` or
> `docs/verification/EDU-PACK-CONFORMANCE.md`, with the section named.** Nothing is estimated,
> extrapolated or re-derived by hand. Measurements I ran myself are labelled as such and carry the
> command that produced them.

---

## 1. What was built

ClaimGuard AI is a pre-submission **review** copilot for a fictional Gulf health-insurance workflow.
It checks a synthetic claim against 15 fictional payer rules, cites the exact value behind every
finding, explains the finding in bounded language, routes it to a human reviewer, and records both
the check and the human action in an append-only, hash-chained ledger. It never approves, denies,
prices, pays or submits a claim.

| Capability (pack "Required MVP behaviour") | Implementation | Where |
|---|---|---|
| 1 · Ingest normalized JSONL; CSV import supplied; one FHIR mapping example | JSONL is authoritative; `csv_source.py` rebuilds the CSV export into the same envelopes; `fhir_source.py` projects a FHIR R4 collection Bundle onto the fields it carries and reports the rest | `claimguard/edu/run.py`, `claimguard/edu/intake/**` |
| 2 · All 15 rules, including uncertainty and not-applicable | `RULE_FUNCTIONS` (R001..R015), five-value status model | `claimguard/edu/rules/**`, `claimguard/edu/engine.py` |
| 3 · Claim ID, Rule ID/version, severity, affected lines, evidence, explanation, corrective action | The frozen 15-key result record | `claimguard/edu/emit.py`, `claimguard/edu/envelope.py` |
| 4 · Review queue with filters, original values, unresolved-check counts | `GET /v1/queue` returns findings with echoed filters and counts | `claimguard/review/app.py`, `claimguard/review/store.py` |
| 5 · Confirm / dismiss with reason / request information / corrected-for-recheck | Four-action state machine; actor and reason required and non-blank | `claimguard/review/models.py`, `claimguard/review/store.py` |
| 6 · One bounded AI capability with tool boundaries, schema checks and a safe fallback | Optional explanation provider; 4-key output contract; citation, prohibition and echo guards; deterministic fallback always available | `claimguard/edu/explain/**` |
| 7 · Record checks and human actions with versions; tamper-evident audit prototype and its limits | Run and decision events appended to the SHA-256 hash-chained ledger; limits documented | `claimguard/review/audit_events.py`, `claimguard/audit/chain.py`, `docs/12-Privacy-and-Security-Note.md` §4 |
| 8 · Evaluate on the provided data; report false alarms, missed issues and uncertainty separately | Versioned evaluation report generated from a real run; the scorer's own JSON is reproduced verbatim | `scripts/edu_report.py`, `docs/verification/EDU-EVALUATION-REPORT.md` |

**Architecture, data-flow, trust boundaries and tool permissions** are in
`docs/11-Architecture-and-Dataflow.md`. **Privacy, security and the honest limits of the ledger** are
in `docs/12-Privacy-and-Security-Note.md`. The reproducible sample run is in
`docs/verification/REPRODUCIBLE-SAMPLE-RUN.md`.

---

## 2. Decisions taken, and why

The two decision records this report defers to are
**`docs/10-ADR-Starter-Pack-Authority.md`** (the mentor pack is the assessment contract) and
**`docs/09-ARCHITECTURE-V2-Decisions.md`** (the v2 architecture decisions and the P0 bug list).

| # | Decision | Why | Record |
|---|---|---|---|
| D1 | The pack's contract is the assessment contract: the 17-key envelope, R001–R015, the five statuses, the 15-key record, `{path, value}` evidence | A machine grades it — the mentor's scorer exits non-zero on any deviation | ADR-10 §2.1 |
| D2 | The pack's scorer is the oracle; a green CI run is **not** sufficient evidence | The scorer is the graded judge; CI never runs it (it needs the pack) | ADR-10 §2.2, §5.1 |
| D3 | The deterministic core is plain Python functions; no autonomous agent loop in the decision path | Replayable runs, testable rules, provable non-adjudication | doc 09 ADR-001 (in `docs/04-Architecture.md` §13), ADR-10 §3 |
| D4 | The model writes language only; it can never set a status, severity, evidence entry or review flag | "Review, don't adjudicate" is a disqualifier boundary, not a preference | ADR-10 §3, `claimguard/edu/explain/__init__.py` |
| D5 | Corrections are new versions, never edits | The pack's non-negotiable checks; a button click must not turn a FAIL into a PASS | ADR-10 §2.6, `claimguard/db/migrations/versions/0002_review_workflow.sql` |
| D6 | The v1 audit ledger is kept and the pack's teaching `audit.py` is **not** adopted; the review workflow appends to the existing chained table | Migration 0001's trigger is the single canonical hash owner and a parity test guards it | ADR-10 §2.3, `claimguard/audit/chain.py` |
| D7 | The two rule worlds never merge (pack `R001–R015` vs the retired `COV-001`-style catalogue) | The identifiers look alike and mean different things; aliasing them would be a silent correctness bug | ADR-10 §2.4 |
| D8 | Additive integration: the pack layer lives in `claimguard/edu/` and takes `--rules-dir`, so no mentor data is hard-coded | The pack is reference material, not our source | ADR-10 §2.5 |
| D9 | FHIR is a demonstration path, not the benchmark path | The projection cannot answer 8 of the 15 rules; the bundle is deliberately insufficient | ADR-10 §4, `claimguard/edu/intake/fhir_source.py` |
| D10 | Edge-case tests are written from the rulebook, not from the gold labels | The public labels cannot discriminate several rule edges; the mentor's held-out set will test exactly there | ADR-10 §4, `tests/edu_edges/test_rulebook_edges.py` |
| D11 | Deterministic checks report `confidence: null` with `confidence_kind: "not_probabilistic"` | The scorer rejects the run otherwise; a deterministic rule is not a probability | ADR-10 §3, `claimguard/edu/envelope.py` |
| D12 | Explanations carry a provenance prefix (`[deterministic] ` / `[model] `) | A reviewer must be able to tell who wrote the text without extra tooling | `claimguard/edu/explain/fallback.py` |
| D13 | The decision's free-text `reason` is **not** copied into the immutable ledger | Reviewer text may quote attachment content; duplicating it into an immutable table widens the data-protection surface for no audit gain | `claimguard/review/audit_events.py` |
| D14 | One deployable service, Docker Compose, no Kubernetes, no microservices | Five people, one month, one demo machine | doc 09 §A3, §A4 |

---

## 3. Test strategy

### 3.1 Two tiers, because the pack is not in git

| Tier | Needs the mentor pack? | What it covers | Where it runs |
|---|---|---|---|
| Engine logic and contract tests | No — the rule catalogue is vendored under `tests/edu/fixtures/pack_reference/` with checksums in `PROVENANCE.json` | Envelope/transport contract, result contract, the 15 rules, rulebook edges, explanation guards, intake, report rendering, reviewer API/store | CI and locally |
| Pack-graded checks | Yes — gold labels and the mentor's strict scorer | Gold-label replay and every conformance-harness self-check | Locally and as a pre-submission gate (`make edu-conformance`); they report **skipped** in CI |

Vendoring was verified: running the engine against the vendored catalogue reproduces the same oracle
result as running it against the pack's own `rules/` directory (`status_accuracy 1.0000`, `fp 0`,
`fn 0`) — `docs/verification/EDU-PACK-CONFORMANCE.md`, §"CI behaviour and vendored fixtures".

**Consequence stated plainly:** CI green does **not** prove mentor-scorer conformance. The
oracle-graded run is a mandatory local step before any submission.

### 3.2 Independent verification, not self-reporting

The conformance harness (`scripts/edu_conformance.py`) runs two opinions and requires both:

1. the mentor's own strict scorer, executed as a subprocess (the authority); and
2. an independent re-implementation of the admissibility contract, which imports no pack code and
   re-checks result shape, literals, review flags, line-id bounds, every evidence pointer re-resolved
   by an RFC 6901 walk against the **original** claim with type-exact equality, per-claim rule
   coverage, and duplicate/unknown claims — and **recomputes** `count/tp/fp/fn/status_accuracy/
   not_implemented` from gold plus predictions, failing on any disagreement with the oracle's JSON.

The harness is also proven to fail loudly. Negative self-checks (mutants built by
`tests/edu_conformance/test_harness_selfcheck.py`) — `docs/verification/EDU-PACK-CONFORMANCE.md`,
§"Negative self-checks":

| Mutant | Oracle | Harness | Signal |
|---|---|---|---|
| Fabricated evidence value (`/invoice_number` → `"INVENTED"`) | exit 2 | exit 1 | evidence value mismatch, named on both sides |
| One claim-rule pair dropped | exit 2 | exit 1 | `Prediction coverage mismatch: 1 missing pairs` |
| `method: "model_assisted"` (the oracle does **not** check `method`) | exit 0 | exit 1 | `result line 1: method must be 'deterministic'` — proof the second opinion is not the oracle |

`uv run pytest tests/edu_conformance -q` → **11 passed**.

### 3.3 Verified versus taken on trust

| Property | Status |
|---|---|
| Result admissibility (key set, literals, review flags, evidence presence, line-id bounds, pointer resolution and value equality, per-claim coverage, duplicate/unknown claims) | **Verified independently** — the harness re-checks it and the oracle enforces it too |
| Metric arithmetic (`count/tp/fp/fn/status_accuracy/not_implemented`) | **Verified independently** by recomputation; a disagreement fails the run |
| `issue_precision/recall/F1`, `false_alarm_rate`, `false_abstentions`, `missed_abstentions`, the per-rule table, the confusion list, `claims_with_all_statuses_correct` | **Taken from the oracle's JSON** — reported, not re-derived |
| Gold status labels | **Taken from the pack** (`data/<split>/expected_results.jsonl`) — the ground truth for status correctness |
| Semantic rule behaviour (does R009 aggregate authorization quantity across lines? is R014's window the latest service date?) | **Taken from the pack** — the harness checks conformance, not the rulebook's intent |
| The claim data itself | **Taken from the pack**, read-only |
| Explanation quality | **Not scored by any script.** The pack requires manual 0/1 scoring of its 25 cases (correct finding, correct evidence, correct rule, appropriate action, honest uncertainty) plus a list of unsupported statements; that scorecard is produced by hand and is not reproducible by a command, so no explanation number appears in this report |

*(Source of this table: `docs/verification/EDU-PACK-CONFORMANCE.md`, §"Independently verified vs taken
from the pack".)*

### 3.4 Suite sizes (measured by me, 2026-09-23)

```bash
uv run pytest <dir> --collect-only -q      # counted per directory
```

```text
tests/edu = 138        tests/edu_edges = 38      tests/edu_explain = 87
tests/edu_intake = 27  tests/edu_report = 24     tests/edu_conformance = 11
tests/review = 78      tests/review_ui = 13      tests/unit = 72
tests/integration = 9
```

Two suites were executed for this report: `uv run pytest tests/review -q` → **78 passed** (run twice, 3.08 s and 3.60 s),
and `uv run pytest tests/edu_explain tests/edu/test_emit_contract.py tests/edu/test_r008_r015.py -q`
→ **161 passed in 5.72s**. **Discrepancy, disclosed:** `docs/verification/EDU-PACK-CONFORMANCE.md`
§"CI behaviour and vendored fixtures" says `tests/edu` holds 137 tests; my collection on 2026-09-23
counted 138. The suite has grown since that line was written; I did not re-pin the old document.

---

## 4. Measured results

### 4.1 Development split — the mentor's scorer, verbatim

`docs/verification/EDU-EVALUATION-REPORT.md`, §"Scorer verdict and gates" (scorer exit **0**,
verdict **CONFORMANT**):

```text
count 6000 · tp 319 · fp 0 · fn 0 · tn 5681
issue_precision 1.0 · issue_recall 1.0 · issue_f1 1.0 · false_alarm_rate 0.0
status_accuracy 1.0 · not_implemented 0 · false_abstentions 0 · missed_abstentions 0
```

| Metric | Value | Source section |
|---|---|---|
| Claim-rule pairs scored | 6000 | §"Metrics", `overall.count` |
| Issue precision / recall / F1 | 1.0000 / 1.0000 / 1.0000 | §"Metrics" |
| False-alarm rate | 0.0000 | §"Metrics" |
| Status accuracy | 1.0000 | §"Metrics" |
| False abstentions / missed abstentions | 0 / 0 | §"Metrics" |
| NOT_IMPLEMENTED predictions | 0 | §"Metrics" |
| Claim exact match (all 15 statuses correct) | 400 / 400 = 1.0000 | §"Claim exact match" |
| Independent admissibility problems | 0 | §"Scorer verdict and gates" |
| Evidence pointers re-resolved against the original claims | 20300 | §"Scorer verdict and gates" |
| Accuracy gate (`--accuracy-scope implemented --min-accuracy 1.0`) | PASS, 1.0000 over 6000 pairs | §"Scorer verdict and gates" |

Confusion matrix (`§"Confusion matrix"`): PASS 5014, FAIL 319, UNABLE_TO_ASSESS 180,
NOT_APPLICABLE 487, NOT_IMPLEMENTED 0 — all on the diagonal, 0 off-diagonal.

Per-rule (`§"Per-rule results"`): all 15 rules show precision, recall, F1, status accuracy `1.0000`,
false-alarm rate `0.0000` and `NOT_IMPLEMENTED 0`. Expected FAIL counts per rule range from 10 (R011)
to 36 (R001).

### 4.2 All three public splits

`docs/verification/EDU-PACK-CONFORMANCE.md`, §"Our engine — `python -m claimguard.edu.run`":

| Split | Claim-rule pairs | Oracle `status_accuracy` | Recomputed | Claims with all 15 correct | Evidence pointers | Result |
|---|---:|---:|---:|---|---:|---|
| development | 6000 | 1.0000 | 1.0000 | 400 / 400 | 20270 | CONFORMANT |
| validation | 2250 | 1.0000 | 1.0000 | 150 / 150 | 1477 | CONFORMANT |
| stress | 750 | 1.0000 | 1.0000 | 50 / 50 | 467 | CONFORMANT |

**Discrepancy, disclosed rather than smoothed:** the development-split evidence-pointer count is
**20300** in `docs/verification/EDU-EVALUATION-REPORT.md` §"Scorer verdict and gates" and **20270** in
`docs/verification/EDU-PACK-CONFORMANCE.md` §"Our engine". Both are real runs of the same harness
recorded at different times; I did not re-run either to reconcile them, and I do not average them.

### 4.3 Reference ablation: the pack's own baseline

The pack ships a 3-rule reference engine (R001, R003, R006). Scored by the same oracle on the same
split — `docs/verification/EDU-EVALUATION-REPORT.md`, §"Reference ablation: the pack's own baseline",
and `docs/verification/EDU-PACK-CONFORMANCE.md`, §"Pack baseline":

| Metric | Our engine | Pack baseline |
|---|---|---|
| Claim-rule pairs | 6000 | 6000 |
| Issue precision | 1.0000 | 1.0000 |
| Issue recall | 1.0000 | 0.2759 |
| Issue F1 | 1.0000 | 0.4324 |
| False-alarm rate | 0.0000 | 0.0000 |
| Status accuracy | 1.0000 | 0.2000 |
| False abstentions | 0 | 0 |
| Missed abstentions | 0 | 156 |
| NOT_IMPLEMENTED | 0 | 4800 |
| Claim exact match | 400 / 400 | 0 / 400 |
| tp / fp / fn / tn | 319 / 0 / 0 / 5681 | 88 / 0 / 231 / 5681 |

The baseline is the mentor's own code, quoted verbatim in the evaluation report as implementing
`R001, R003, R006` with every other rule `NOT_IMPLEMENTED`. It is a floor for comparison, not a
criticism: its `status_accuracy 0.2000` is exactly what the scorer's design produces when 4800 of
6000 pairs are visibly unimplemented.

### 4.4 Error analysis

`docs/verification/EDU-EVALUATION-REPORT.md`, §"Error analysis": `false_alarm 0`, `missed_issue 0`,
`false_abstention 0`, `missed_abstention 0`, `other_status_disagreement 0` — 0 of 6000 status
disagreements. The pack's report template asks for at least five false or missed findings *with Claim
ID, Rule ID and evidence*; **we have none to show and we do not manufacture them.** The report says so
in those words and substitutes the reference ablation: the pack baseline's 231 missed issues are
enumerated by claim and rule in §"Error analysis" (first 25 listed, missed issues first), with the
evidence column honestly empty because `NOT_IMPLEMENTED` carries no evidence.

### 4.5 Where the evidence is thin

`docs/verification/EDU-EVALUATION-REPORT.md`, §"Support: which rules carry the thinnest evidence":
the thinnest positive support is **R011** (10 expected FAIL of 400 pairs), then **R002** (11) and
**R008** (11); the thinnest discriminating support is **R011** (10 non-PASS labels), **R002** (19),
**R012** (23). A perfect score on R011 rests on ten observations, and a single flip moves its recall
by 10.00 points. Read with §5 below, this is the honest shape of a 1.0000.

### 4.6 Human review and the AI layer

* **Human review is measured behaviourally, not statistically.** For this report I exercised the
  reviewer API against the live database: `GET /v1/health` 200 (schema `0002`), `POST /v1/claims`
  201 with 15 records and `by_status {'PASS': 14, 'FAIL': 1}`, a blank-reason decision rejected with
  422, a valid decision accepted with 201, `GET /v1/queue` reporting
  `{"findings": 1, "unresolved": 0, "resolved": 1}`, and `UPDATE`/`DELETE` on the result and
  decision tables refused by the database. Full transcript:
  `docs/11-Architecture-and-Dataflow.md` §9.1(b).
* **The AI layer is ablation-shaped, not score-shaped.** The pack's AI evaluation requires manual
  0/1 scoring of explanation cases; that scorecard is produced by hand elsewhere and no explanation
  number is claimed here. What is verified structurally: the explanation output carries exactly four
  keys, its cited evidence paths must be a subset of the finding's supplied paths, its cited rule id
  must equal the finding's, its review flag must equal the finding's own, and any failure falls back
  to the deterministic explanation with the fallback marked. A model failure changes **0** statuses
  (`tests/edu_explain/test_status_invariance.py`), and a model is never even consulted for a `PASS`
  (`MODEL_ELIGIBLE_STATUSES = {"FAIL", "UNABLE_TO_ASSESS"}`).
* **No latency, cost or token figure is reported**, because none was measured with a live model in
  this repository.

---

## 5. Limitations

### 5.1 The pack's honesty rules, restated

Quoted from `docs/verification/EDU-EVALUATION-REPORT.md`, §"Honesty rules and limitations":

* **Instructional oracle, not ground truth.** The labels are an instructional oracle for a fictional
  rulebook: neither clinical ground truth nor reimbursement ground truth, and agreement with them is
  not evidence of production readiness.
* **Dataset split.** This report covers the development split (400 claims, 6000 claim-rule pairs) of
  the supplied synthetic teaching dataset; the mentor's 200 held-out claims were not used and are not
  reachable from this repository.
* **Labels cannot discriminate every edge.** Cross-line authorization quantity aggregation; R007's
  0.01 tolerance at a rounding boundary; whitespace-only strings against a non-empty check; claims
  whose lines carry several service dates; precedence between a proven violation and an unknown input
  on the same rule.
* **Evidence values do not prove relevance.** Re-resolving every pointer proves the cited value
  exists and is exact; it does not prove the cited field is relevant to the conclusion.
* **Explanations are scored manually** — not by the generator.
* **NOT_IMPLEMENTED counts as incorrect** — the scorer treats it as wrong.
* **Synthetic data only, review not adjudication** — the system never approves, denies, prices or
  pays, and nothing here is clinical advice.
* **Undefined metrics are null** — a precision, recall or rate with an empty denominator prints
  `null`, never 100%.

### 5.2 Our own limitations, from the conformance record

Quoted from `docs/verification/EDU-PACK-CONFORMANCE.md`, §"Honest limitations":

1. **The mentor's scorer is the oracle.** The independent checks are a second opinion on
   admissibility and metric arithmetic, not a superior judgement. A systematically wrong engine that
   happened to reproduce the shipped labels would still pass.
2. **Evidence relevance is not proved** — that needs human review.
3. **Explanation quality is out of scope** of every automated check.
4. **Sibling outputs are snapshots** — re-run the harness after any engine change; there is no CI
   wiring for the oracle run.
5. **The harness is stricter than the oracle in a few contract-literal places** (`method`,
   `review_status`, `requires_human_review`/`corrective_action` typing, non-empty `explanation`, the
   17-key envelope).
6. **The gate metric is chosen deliberately** — `--min-accuracy 1.0` means "every status the engine
   committed to is exactly right", not "every pair is implemented"; `--accuracy-scope total` gates
   the raw number, and an all-`NOT_IMPLEMENTED` file scores 0.0 and fails.
7. **Split selection is fixed** to the three shipped splits; the mentor's private 200 held-out claims
   are unreachable by design.

### 5.3 Limitations we add ourselves

* **The 1.0000 is a statement about a synthetic, fictional rulebook.** It is not a claim about real
  payer rules, real claims, or real denial rates. **No real-world denial reduction is claimed,
  measured or implied anywhere in this submission.**
* **Public labels cannot discriminate rule edges**, so a wrong implementation of an edge could still
  score 1.0000. We answer that with rulebook-derived edge tests
  (`tests/edu_edges/test_rulebook_edges.py`, 38 tests) rather than with a better number.
* **CI does not run the oracle.** Green CI is not conformance evidence.
* **The security posture is a prototype** (no authentication, no authorisation, no encryption at
  rest, no retention lock). See `docs/12-Privacy-and-Security-Note.md` §5.
* **The held-out assessment has not happened.** Per `docs/10-ADR-Starter-Pack-Authority.md` §7, the
  mentor's 200 claims remain outstanding, and the reproducibility package (video, pitch) is due at
  the Phase-1/Phase-3 gates.
* **No explanation-quality number exists** in this report, on purpose: it would have to be invented.

---

## 6. Reproduction

```bash
# Engine over the development split (needs the mentor pack present)
uv run python -m claimguard.edu.run \
  --claims ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/data/development/claims.jsonl \
  --rules-dir ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/rules \
  --output artifacts/edu-report/development/predictions.jsonl

# Both opinions: the mentor's scorer plus the independent harness
uv run python scripts/edu_conformance.py \
  --pred artifacts/edu-report/development/predictions.jsonl --split development \
  --accuracy-scope implemented --min-accuracy 1.0

# Regenerate the evaluation report from a real run
uv run python scripts/edu_report.py --split development \
  --output docs/verification/EDU-EVALUATION-REPORT.md

# The reviewer workflow suite (needs PostgreSQL)
uv run pytest tests/review -q

# Minimal end-to-end sample run (submit one claim, read its findings, record a decision)
CLAIMGUARD_DATABASE_URL="postgresql+psycopg://claimguard:claimguard@localhost:5432/claimguard" \
  uv run python scripts/sample_run.py
```

The literal argv, exit codes and full stderr of the recorded run are preserved verbatim in
`docs/verification/EDU-EVALUATION-REPORT.md` §"Reproduction"; the harness commands are in
`docs/verification/EDU-PACK-CONFORMANCE.md` §"Exact commands". A minimal end-to-end sample run is in
`docs/verification/REPRODUCIBLE-SAMPLE-RUN.md`.

---

## 7. What I could not verify

* I did not re-run the engine, the mentor's scorer or the conformance harness for this document: the
  numbers in §4 are the ones those two reports record, cited by section, and re-running them here
  would not have changed them. Everything I *did* run is labelled with its command.
* I did not reconcile the 20300 / 20270 evidence-pointer difference (§4.2).
* I did not run the pack's manual explanation scorecard, so no explanation-quality claim is made.
* I did not run `docker compose up`; the compose/Dockerfile entry points do not match the tree
  (see `docs/11-Architecture-and-Dataflow.md` §9.3).
* No performance, latency, cost or capacity measurement exists in this repository.
