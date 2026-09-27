# Phase-1 gap analysis — what is required, what we shipped, what is missing

> **Purpose:** decide, five days before the Phase-1 gate, whether we can claim every point we
> intend to claim — and close anything that is missing.
> **Method:** every "shipped" row names an artifact that exists in this repository and, where a
> number is quoted, the command that produced it. Rows were re-verified on 2026-09-26 against the
> current `main`, not copied from the completion report.
> **Requirement sources:** three, and they are not the same thing.
> 1. **Official CSTAM scoring** — 50 points across four items (`docs/03` §3.1, from the CSTAM Book).
> 2. **The mentor pack's contract** — 8 Required MVP behaviours and a 7-item submission checklist
>    (`<pack>/docs/01_Challenge_Brief.md`).
> 3. **The pack's 5 non-negotiable demonstration checks** (`<pack>/docs/07_Evaluation_and_Acceptance.md`).
>
> The mentor's proposed assessment weights (rule correctness 35 / grounded AI 20 / human review 15 /
> uncertainty and security 15 / audit and reproducibility 10 / communication 5) are **proposals the
> pack itself says are not official**. They are useful as a lens, not as the rubric — see §6.

---

## 1. Official scoring — 50 points

| # | Requirement (near-verbatim) | Pts | What we shipped | Evidence I ran or read | Status |
|---|---|---:|---|---|---|
| 1 | Ingest and normalize synthetic claim data (JSONL, CSV, canonical normalization, envelope handling) | 15 | Authoritative JSONL intake; CSV rebuilt from the relational export; FHIR R4 projection with a declared unsupported list; malformed input quarantined with structured errors | `python -m claimguard.edu.run` over all three splits; CSV rebuild is **exactly equal** to the pack's own `claims.jsonl` (400 / 150 / 50 records) with **0 status differences**; `tests/edu_intake/**` | **Met** |
| 2 | A deterministic + AI rule engine that catches the administrative problems | 15 | All 15 rules `R001`–`R015` with the five-value status model; bounded AI assistance over findings | The mentor's own scorer, all three splits: **status_accuracy 1.0000**, issue F1 1.0000, fp 0, fn 0, missed abstentions 0 — **9000/9000 labels** | **Met** |
| 3 | Explainable structured output: claim ID, rule ID, rule-linked evidence, severity, confidence, suggested corrective action | 10 | The frozen 15-key result record; evidence as `{path, value}` re-resolved against the original envelope | `claimguard/edu/envelope.py`, `emit.py`; the scorer re-resolves every pointer and rejects the run if a value does not match | **Met** |
| 4 | An audit log engine: append-only, tamper-evident, **replayable** history | 10 | Append-only `claimguard.audit_events` with a SHA-256 hash chain enforced by a Postgres trigger; run-level and decision-level events carry input hash, rule/model/prompt versions; Python and SQL digests proven identical against live Postgres | `tests/integration/test_audit_trigger_parity.py` (5 tests, three consecutive green runs against a non-empty ledger); **replay demonstrated** — `scripts/audit_replay.py` reconstructs a stored run from the ledger and verifies the chain (`docs/verification/AUDIT-REPLAY.md`); `docs/12` §4 states the limits | **Met** |

**Gap G3 (audit replay) — closed 2026-09-26.** The word *replayable* is in the scored requirement, and
until now nothing demonstrated it: a reviewer asking "show me replay" got a description, not a
transcript. `scripts/audit_replay.py` now reconstructs a stored run from its immutable envelope,
re-runs the engine, compares all 15 records field by field, and walks the run's ledger rows —
content, linkage and agreement with the run row — with a captured transcript in
`docs/verification/AUDIT-REPLAY.md`. **Replaying an older, real run exposed a bug in the first
version** of that walk (it compared a run's events to each other instead of to the global ledger,
which false-alarmed on any interleaved run); the rule is corrected and pinned by a test.

---

## 2. The pack's 8 Required MVP behaviours

| # | Requirement | What we shipped | Evidence | Status |
|---|---|---|---|---|
| 1 | Ingest normalized JSONL; CSV import; **demonstrate one FHIR mapping example** | JSONL and CSV fully working; the FHIR projection recovers 30 of 41 envelope leaf paths and reports the other 11 rather than inventing them | CSV rebuild byte-equal; `claimguard/edu/intake/fhir_source.py` + its tests; **demonstration** — `scripts/fhir_example.py` over one real bundle with a captured transcript (`docs/verification/FHIR-MAPPING-EXAMPLE.md`) showing the 30 recovered paths, the 11 unsupported ones, and which checks that blocks | **Met** |
| 2 | Evaluate all 15 rules including uncertainty and not-applicable outcomes | Five-value status model with the rulebook's precedence (`FAIL` > `UNABLE_TO_ASSESS` > `PASS`/`NOT_APPLICABLE`) | 1.0000 status accuracy; `tests/edu_edges/**` (38 tests over the edges the public labels cannot reach) | **Met** |
| 3 | Report claim ID, rule ID/version, severity, affected lines, evidence, explanation, corrective action | Exactly those fields, frozen in the 15-key record | Scorer rejects any extra or missing key | **Met** |
| 4 | Review queue with filters, original values, unresolved-check counts | Queue with status/severity/rule filters, echoed filters, counts, and evidence shown as `path = value` read from the original claim | `GET /v1/queue`; verified live in the cockpit (13 claims / 29 findings) | **Met** |
| 5 | Confirm, dismiss with reason, request information, corrected-for-recheck | Four-action state machine; actor and reason required and non-blank; a correction creates a new version | Verified live: four malformed decisions → 422, a valid decision → 201, queue 29 → 28 unresolved / 1 resolved | **Met** |
| 6 | One bounded AI capability with tool boundaries, schema checks and a safe fallback; never relabel deterministic failures through an LLM | Model-first explanation plus correction recommendation under an exact five-key contract, with citation, invariant, adjudication, automatic-action and injection guards, and a labelled deterministic safe twin | `claimguard/edu/explain/verifier.py`; the model-isolation invariant verified: 15 keys exactly and **no field other than `explanation` differs** from the engine's output | **Met** |
| 7 | Record checks and human actions with source/rule/model versions; tamper-evident audit prototype and the additional controls needed for production | Run and decision events with input hash and versions; limits documented rather than glossed | `claimguard/review/audit_events.py`; `docs/12` §4 | **Met** |
| 8 | Evaluate on the provided data, **then on a mentor-held set**; report false alarms, missed issues and uncertainty separately | All three provided splits evaluated with false alarms, missed issues, false and missed abstentions reported separately; a versioned report that refuses to render when the scorer rejects the run | `docs/verification/EDU-EVALUATION-REPORT.md` | **Partial — half is impossible for us** |

**Gap G1 (FHIR demonstration) — closed 2026-09-26.** The behaviour says *demonstrate*; a code path plus
tests is not a demonstration. `scripts/fhir_example.py` now runs one real bundle end to end and prints
the recovered fields, the module's own unsupported list, and the rule-level consequence (13 of 15
checks answerable; R009 and R010 are not), captured verbatim in
`docs/verification/FHIR-MAPPING-EXAMPLE.md`.

**Gap G5 (mentor-held set).** Not obtainable: the pack states the 200 held-out claims are held by the
mentor. **This cannot be closed by us** — it can only be stated honestly, which `docs/20` §10 does.
*Risk reduced, not closed, 2026-09-27:* the pack's splits are representative rather than adversarial,
so 87 hand-built boundary cases now probe the edges the rulebook words precisely (inclusive dates,
0.01 SAR tolerances, equality at a maximum, null-modifier normalization). All 87 behave as the
rulebook says — `docs/verification/ADVERSARIAL-CASES.md`. That is evidence about the *edges*, not
about the mentor's unseen 200 claims, and it does not become evidence about them by being written down.

---

## 3. The pack's submission checklist

| # | Requirement | What we shipped | Evidence | Status |
|---|---|---|---|---|
| 1 | Reproducible repository: README, dependencies, configuration example, launch commands | README with a quickstart; `uv.lock` committed; `.env.example` documenting every setting actually read; a console with `status` / `serve` / `evaluate` / `report` | `uv run claimguard status` → `RESULT: ready`; `docker compose config` valid | **Met** |
| 2 | Architecture and data-flow diagram with trust boundaries and tool permissions | `docs/11` — pipeline, module map, Mermaid diagrams, trust boundaries, what the model may and may not touch | Read and checked against the code | **Met** |
| 3 | Working review interface, **recorded demo** and a **concise pitch presentation** | The Next.js cockpit works end to end (verified live against a real API in a browser); the 7-minute demo script exists with a fallback path and Q&A answers | `frontend/` + 11 vitest tests + the live verification recorded in `docs/20` §9; `docs/15` | **Partial — two artifacts missing** |
| 4 | Technical report covering implementation, decisions, tests and limitations | `docs/13` — decisions with rationale, test strategy, what is verified vs taken on trust, limitations | Read; every cited path resolves | **Met** |
| 5 | Evaluation report with dataset split, rule metrics, false positives/negatives and **AI ablations** | The report covers the split, per-rule metrics, false alarms and missed issues, and ablates against the pack's own baseline. It states explicitly that it scores only the deterministic engine | `docs/verification/EDU-EVALUATION-REPORT.md` §"Reference ablation"; **AI ablation now measured** — `scripts/ai_ablation.py` compares the deterministic path against a failing-model path over all 6000 development findings and proves the status-change count is 0 (`docs/verification/AI-ABLATION.md`) | **Met** |
| 6 | Privacy/security note and an auditable sample run | `docs/12`; a reproducible sample run with a captured transcript | `docs/verification/REPRODUCIBLE-SAMPLE-RUN.md`; `uv run python scripts/sample_run.py` | **Met** |
| 7 | Contribution log explaining team roles and the use of AI coding tools | `docs/14` | Read | **Met** |

**Gap G2 (recorded demo).** Blocking for the checklist and for the pitch. **Human task** — recording,
not code.

**Gap G4 (pitch presentation).** Same. **Human task.**

**Gap G6 (AI ablation) — closed 2026-09-26.** The report ablated the pack's baseline, which is a
*system* ablation; the mentor asks for an **AI** ablation. `scripts/ai_ablation.py` now measures both
the contribution and the failure mode of the assistance layer over a real split: on the deterministic
path 6000/6000 explanations are accepted; with the model unavailable 499 findings fall back to the
deterministic text and 5501 are declined because `PASS`/`NOT_APPLICABLE` are not model-eligible — and
**0 of 6000 statuses move on either path**, confirmed across all three splits (0 of 9000). Captured in
`docs/verification/AI-ABLATION.md`, which also states what remains unmeasured.

---

## 4. The pack's 5 non-negotiable demonstration checks

These are pass/fail in spirit: failing one undermines everything else.

| Check | How we satisfy it | Evidence | Status |
|---|---|---|---|
| No unimplemented or unknown check is represented as a pass | Five distinct statuses; `NOT_IMPLEMENTED` is surfaced as its own state and never rendered as a pass | The cockpit's status legend and the queue's `by_rule_status` counts | **Met** |
| Each flagged issue links to source evidence and the applicable fictional rule | Every result carries `rule_source` and evidence pointers that must re-resolve | The scorer rejects the run on any value mismatch | **Met** |
| A model failure cannot remove a deterministic finding | The assistance layer may rewrite prose only; a failure falls back to the deterministic text | Verified: 2250 enrichments across 6 provider failure shapes changed **0** immutable fields | **Met** |
| The original input is preserved and a correction is rechecked as a new version | Corrections create a new run; the original run, results and decisions stay retrievable | Verified live (version 2 beside version 1) | **Met** |
| No real patient information, exposed credential or live payer submission appears in the demo | Synthetic-only; no credential in any tracked file; there is no payer-submission path in the codebase | `gitleaks` in CI; the demo script's scope section | **Met** |

---

## 5. The gap list

| ID | Gap | Severity | What closing it takes | Who |
|---|---|---|---|---|
| **G2** | **Recorded demo video** | **Blocking** — an explicit checklist item, and the pitch depends on it | One recording session against `docs/15`; the stack runs offline | Human |
| **G4** | **Pitch presentation** | **Blocking** — an explicit checklist item | Build the deck from verified numbers only (`docs/20` §9, `docs/verification/EDU-EVALUATION-REPORT.md`); 5 + 2 + 5 minutes | Human |
| ~~**G3**~~ | ~~Audit replay not demonstrated~~ | ~~High~~ | **Closed 2026-09-26** — `scripts/audit_replay.py` + `docs/verification/AUDIT-REPLAY.md`; the walk also caught and fixed a false-alarm bug | Done |
| ~~**G1**~~ | ~~FHIR mapping example not demonstrated~~ | ~~Medium~~ | **Closed 2026-09-26** — `scripts/fhir_example.py` + `docs/verification/FHIR-MAPPING-EXAMPLE.md` | Done |
| ~~**G6**~~ | ~~AI ablation missing from the evaluation~~ | ~~Medium~~ | **Closed 2026-09-26** — `scripts/ai_ablation.py` + `docs/verification/AI-ABLATION.md` (0/6000 statuses moved on either path) | Done |
| **G5** | Held-out evaluation | **Unclosable** | The mentor's 200 claims are not reachable. State it; never fake it | Mentor |
| — | Human explanation-quality scoring (the pack's 25 cases) | Medium — 20 of the mentor's proposed points | Hand-score with the pack's scorecard; this is the B1 lab | Team |

**Nothing else is missing.** Everything not listed above has an artifact that exists and was
re-verified today.

---

## 6. Reading the mentor's proposed weights honestly

If the mentor assesses against their own weights, two rows are not yet backed by evidence:

- **Grounded AI explanations (20 of 100)** — the pack requires *manual* 0/1 scoring of its 25 cases.
  No script can substitute for it, and none was attempted. This is the single largest unearned block
  in the mentor's lens.
- **Communication (5 of 100)** — the deck (G4).

Everything else — rule correctness 35, human review 15, uncertainty and security 15, audit and
reproducibility 10 — is backed by evidence that was measured, not asserted.

---

## 7. The five days to 1 October

| When | What |
|---|---|
| **Day 1** | G1, G3 and G6 closed 2026-09-26. Score the pack's 25 explanation cases by hand — the only route to the mentor's 20-point explanation block, and the last unearned item. |
| **Day 2** | Build the deck (G4) **from the verified tables only**. Record the demo (G2) against `docs/15`. |
| **Day 3** | Rehearse the demo twice, offline, from a clean checkout. Re-run the conformance gate on the frozen commit. |
| **Day 4** | Freeze: tag the submission commit, export the evaluation report, assemble the package. |
| **Day 5** | Submit. Buffer only. |

**One rule for the last two days: no new features.** The submission is judged on whether a reviewer
can understand and verify what exists — not on how much exists.

---

## 8. What this analysis does not claim

- It does not claim the system is accurate on real claims. The 1.0000 is agreement with an
  instructional oracle on synthetic data, and several rule edges **cannot be discriminated by the
  public labels at all** — a wrong implementation would still read 1.0000. The mentor's held-out set
  is the only real test, and we have not seen it.
- It does not claim explanation *quality*. That is measured by hand, by the mentor's own rule, and it
  has not been done yet.
- It does not claim production readiness: no authentication, no tenancy, no deletion-proof storage,
  no payer integration — all listed as explicit non-claims in `docs/20` §10.
