# 10 — ADR: Mentor starter pack is the assessment contract (and how it coexists with our build)

> **Status:** **Accepted** — signed off by the Head-of-Project, 2026-09-22.
> **Date:** 2026-09-22 · **Owner:** HeadOfProject
> **Supersedes:** the rule-catalogue and output-contract assumptions in `03` §2 (`COV-001…ENV-001`,
> merged 16-entry table), `05` §5–§7 (YAML+CEL catalogue, self-built mutation benchmark) and
> `06` §5.B (finding-only output). Those documents remain valid as *history and rationale*; where
> they conflict with this ADR, **this ADR wins.**
> **Evidence:** the pack was verified before this decision — 77/77 `SHA256SUMS.json` entries match,
> `src/validate_pack.py` passes, 11/11 pack tests pass, and an independent 15-rule oracle reproduces
> all 9000 public gold statuses. Full record: `docs/verification/EDU-PACK-CONFORMANCE.md`.

---

## 1. Context

On 17 Sep 2026 the mentor (Dr. Wael Hilali) issued the **ClaimGuard AI Student Starter Pack v1.0.0**:
600 labelled synthetic claims, a 15-rule fictional rulebook, a strict scorer, schemas, a baseline
engine, a review page, an audit prototype and an LLM adapter seam.

We had independently designed a *different* contract: a Velodoc-fixture-derived catalogue
(`COV-001`, `AUTH-004`, `DUP-002`, …) over a FHIR-shaped canonical model, a findings-only output,
self-built benchmark and calibrated float confidence. Before the pack arrived, docs/03 §8 asked the
mentors whether the benchmark dataset would be supplied; **the pack answers that question: it is
supplied, with 200 further claims held back for assessment.**

Two consequences follow. The assessment surface is now specified by a machine (a scorer that exits
non-zero on any deviation), and the parts of our plan that existed only to compensate for missing
data are no longer the best use of the remaining days.

---

## 2. Decision

1. **The pack's contract is the assessment contract.** Implement — exactly — the normalized JSONL
   envelope, the `R001`–`R015` rulebook, the five-value status model, the 15-key result record, the
   `{path, value}` evidence convention, and the scorer's literal fields (`rule_version` `"1.0.0"`,
   `rule_source` `"fictional-rulebook/<RULE_ID>@1.0.0"`, `confidence: null` with
   `confidence_kind: "not_probabilistic"`, `method: "deterministic"`, `review_status: "unreviewed"`).
2. **The pack is the oracle.** Acceptance for the deterministic core is *the mentor's own scorer
   exiting 0 with `status_accuracy 1.0000` on all three public splits* — plus our independent
   second opinion. A green CI run is **not** sufficient evidence (see §5).
3. **Our foundation is kept, not replaced.** The append-only PostgreSQL audit chain with its
   SHA-256 trigger-parity test, the FHIR bundle index/resolver, the CI/lint/type discipline and the
   safety posture outlive this pivot. The pack's `audit.py` is a weaker teaching prototype and is
   **not** adopted.
4. **The two rule worlds do not merge.** `R001`–`R015` are the graded rules. The legacy
   `COV-001`-style catalogue is retired from the implementation path and is never silently aliased
   onto the pack's identifiers — the numbering collides in appearance but not in meaning
   (pack `R003` = coverage; Velodoc `R03` = provider network).
5. **Additive integration, no destructive rewrite.** The pack layer lives in `claimguard/edu/`; it
   consumes a `--rules-dir`, so it does not hard-code the mentor's data. Nothing on the existing
   import graph changes until a caller is migrated deliberately.
6. **Corrections are new versions.** A reviewer's correction produces a new input version and a
   rerun; the original envelope and its evidence pointers are never mutated.

---

## 3. What this changes in practice

| Area | Before | After |
|---|---|---|
| Benchmark data | Self-built 50-claim mutation set (doc `05` §7) | **Supplied**: 400 dev / 150 validation / 50 stress + 200 held out. The mutation generator is retired as unnecessary work |
| Rule catalogue | 16 internal rules over FHIR fixtures | `R001`–`R015` over the normalized envelope |
| Rule identifiers | `COV-001`, `AUTH-004`, … | `R001`…`R015`, quoted verbatim in output |
| Output unit | A `Finding` emitted only on a problem | A **result for every claim × rule** (15 per claim) with PASS / FAIL / UNABLE_TO_ASSESS / NOT_APPLICABLE |
| Confidence | Float, `1.0` for deterministic rules (FR-016) | `null` + `not_probabilistic` — the scorer *rejects the whole run* otherwise |
| Severity | `info/minor/major/critical` | `high/medium/low` |
| Currency | Defaulted to `AED` | Taken from the claim/policy (`SAR` in the pack) |
| Metrics | Macro F1 + calibration suite | Issue precision/recall/F1, false-alarm rate, status accuracy, false/missed abstentions, claim exact match |
| Authority question | Open (docs/03 §8 Q1) | **Answered by the pack**: the dataset is provided |

**Kept unchanged and still binding:** review-don't-adjudicate; synthetic data only; evidence-first
findings; append-only audit; the LLM explains and never decides; no clinical output; no payer
submission; no autonomous adjudication.

---

## 4. Consequences — accepted deliberately

- **Work retired on purpose.** The planned mutation generator, the Velodoc-fixture catalogue, the
  YAML+CEL rule manifests and the self-built 50-claim benchmark are no longer on the critical path.
  This is a saving, not a loss.
- **`test_accuracy_gap`.** The public labels cannot discriminate several rule edges (cross-line
  authorization aggregation, R007's cent tolerance, whitespace-only strings, multi-date claims,
  mixed unknown+violation precedence). We implement the rulebook's stated semantics and **write
  edge-case tests from the rulebook, not from the gold** — the mentor's held-out set will test
  exactly there.
- **FHIR is a demo path, not the benchmark path.** The projections cannot answer 8 of the 15 rules,
  so FHIR ingestion is used for the required integration demonstration only.
- **CI coverage is tiered.** Pack-graded tests skip without the pack; the oracle run is a mandatory
  local/pre-submission gate.
- **One catalogue, one namespace.** If the mentors later reinstate the Velodoc fixture catalogue, it
  enters as a *separate* namespaced catalogue with its own decision record — never merged.

---

## 5. Verification obligations that follow

1. `make edu-conformance` green — mentor scorer exit 0, `status_accuracy 1.0000` on
   development, validation and stress, plus the independent harness reporting 0 problems.
2. Edge-case suite for the rulebook edges the public data does not exercise.
3. A fabricated-evidence and a missing-pair case must **fail** the harness (the negative tests).
4. Malformed input must quarantine with a structured ingestion error, never crash and never invent
   a PASS.
5. Untrusted `notes`/attachment text must provably not alter any status.
6. Every gate re-run before the 27 Sep freeze; nothing merged on assertion alone.

---

## 6. Open questions dispatched to the mentor

1. Confirm `R001`–`R015` + normalized JSONL is the assessment contract, superseding the earlier
   facility's rule interpretation where they differ.
2. Which split is used for Phase-2 assessment — the 150-claim validation set or the 200 held-out
   claims — and is the hidden set drawn from catalogue v1.0.0?
3. Model access for the bounded-AI milestone, and whether an offline prototype is acceptable.

Until answered, we implement the pack's published contract and keep the official CSTAM calendar
(freeze 27 Sep, Phase-1 submit 1 Oct). The pack's own four-week plan and 35/20/15/15/10/5 weights are
treated as proposals, exactly as the pack itself states.

---

## 7. Current compliance status

Every row below was re-verified by the lead with pasted command output; nothing
here is an agent's claim. Detail: `docs/verification/EDU-PACK-CONFORMANCE.md` and
`docs/verification/EDU-EVALUATION-REPORT.md`.

| Obligation | Status |
|---|---|
| Pack contract implemented (`claimguard/edu/`, 15 rules) | **Done** — verified |
| Mentor scorer: development / validation / stress | **1.0000 / 1.0000 / 1.0000**, exit 0, fp 0, fn 0, 0 missed abstentions |
| Independent harness second opinion | **CONFORMANT** × 3, 0 problems |
| Ingestion-error quarantine path | **Done** — injected malformed line + missing key → structured errors, exit 2, no invented PASS |
| Untrusted text cannot change a status | **Done** — notes and attachment text proven inert |
| Edge-case suite (rulebook edges gold cannot reach) | **Done** — 38 tests, all 14 edges, 16 mutation probes proving they discriminate |
| CSV intake (MVP behaviour 1) | **Done** — rebuild is byte-equal to the pack JSONL; 0 status mismatches on all splits |
| FHIR mapping demonstration (MVP behaviour 1) | **Done** — 30 of 41 leaf paths projected; the other 11 reported as unsupported, never invented |
| Review queue + four decisions (MVP behaviours 4, 5) | **Done** — verified end to end; malformed decisions 422, valid 201 |
| Run-level audit of checks and decisions (MVP behaviour 7) | **Done** — new tables + events in the existing hash-chained ledger |
| Bounded AI explanation + citation verification (MVP behaviour 6) | **Done** — adversarial outputs rejected; model failure changes 0 statuses |
| Evaluation report (MVP behaviour 8) | **Done** — refuses to report a rejected run; baseline ablation included |
| Reproducibility package (README, diagrams, demo video, pitch) | **Outstanding** — due at the Phase-1/Phase-3 gates |
| Held-out assessment (the mentor's 200 claims) | **Outstanding** — not reachable by us by design |

**Honest limits carried forward:** the public labels cannot discriminate several
rulebook edges, so a wrong implementation could still score 1.0000; evidence-value
checks do not prove the cited field is *relevant*; explanation quality is scored by
hand; and CI green does not prove mentor-scorer conformance, which is why
`make edu-conformance` is a mandatory step in the freeze checklist.
