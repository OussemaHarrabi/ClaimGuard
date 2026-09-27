# ClaimGuard AI — CSTAM-VELODOC

Trustworthy Agentic Copilot for Healthcare Claim Pre-Validation.

Challenge by **Velodoc (Amazit FZCO, Dubai)** for **CSTAM 3.0** — IEEE Computer Society ENET'Com, Hammamet, Tunisia.

Mentors: Dr. Wael Hilali (CTO) · Bilel Said (CEO)

---

## Dates — non-negotiable

| Milestone | Date |
|---|---|
| **Registration closes** | **5 Sept 2026** |
| Phase 1 — MVP (50 pts) | **1 Oct 2026** |
| Phase 2 — Integration & Testing (30 pts) | **20 Oct 2026** |
| Phase 3 — UI/UX & Docs (10 pts) — **selection gate** | **1 Nov 2026** |
| Finals — Pitching (10 pts) | **14–15 Nov 2026** |

Late submission: **−5 pts**. Pitch: max 2 members, English, 12 min (5 + 2 demo + 5 Q&A).
Hard feature freeze for the Phase-1 gate: **27 Sep 2026**.

---

## The one-sentence idea

ClaimGuard sits **between claim creation and payer submission** — it catches the administrative
problems the payer would catch, quotes the exact rule and evidence, recommends the fix, and routes
uncertain cases to a human. **Review, don't adjudicate.**

---

## Quickstart

```bash
uv sync --all-extras                                   # install (Python 3.11–3.13)
docker compose up -d db && uv run alembic upgrade head # the review schema
uv run claimguard status                               # one screen: is this checkout ready?
```

Two ways to point the engine at a rule catalogue: the mentor pack on disk
(`CLAIMGUARD_PACK_ROOT`, gitignored reference material) or the committed copy at
`tests/edu/fixtures/pack_reference/`.

```bash
uv run claimguard evaluate --split all                 # engine + the mentor's own scorer
uv run claimguard report --split development \
    --output docs/verification/EDU-EVALUATION-REPORT.md
uv run claimguard serve                                # API at /v1; legacy fallback at /review
cd frontend && npm ci && npm run dev                   # primary reviewer workspace on :3000
uv run python scripts/sample_run.py                    # end-to-end demo transcript, no network
uv run pytest tests/ -q                                # full Python verification suite
```

---

## What is built

| Piece | Where | State |
|---|---|---|
| Deterministic rule engine — all 15 pack rules `R001`–`R015` | `claimguard/edu/` | **Verified**: the mentor's own strict scorer accepts our output with **status accuracy 1.0000**, issue F1 1.0000, **0 false alarms, 0 missed issues**, 400/400 claims fully correct on development; same on validation and stress (9000/9000 public labels) |
| Independent conformance harness (second opinion, no pack import) | `scripts/edu_conformance.py` | **CONFORMANT** on all three splits, 0 problems |
| CSV intake + educational FHIR projection | `claimguard/edu/intake/` | CSV rebuild is **byte-equal** to the pack's JSONL; FHIR recovers 30 of 41 leaf paths and reports the other 11 as unsupported rather than inventing them |
| Reviewer workflow (runs, results, queue, decisions, corrections) | `claimguard/review/` + migration `0002` | Verified end to end: submit → 15 results; malformed decisions 422; correction → new version, original untouched |
| Reviewer interface | `frontend/` (Next.js) | Evidence-first three-column cockpit; queue, findings, AI provenance and audit visible together; reasoned decisions; immutable correction→recheck. Legacy `/review` remains a fallback. |
| Bounded explanation layer (LLM may rewrite, never decide) | `claimguard/edu/explain/` | Adversarial outputs rejected; a model failure changes **zero** statuses (2250 enrichments tested) |
| JEV advisory sidecar | `claimguard/edu/judge/` + `claimguard judge` | Typed grounding/agreement/attention second opinion; offline-safe without credentials; cannot enter the graded 15-key record. Live quality is not claimed until access and evaluation. |
| Append-only audit ledger (SHA-256 hash chain) | `claimguard/audit/` + migration `0001` | Trigger/Python digest parity proven against live Postgres |
| Edge-case suite for the rulebook edges the public labels cannot reach | `tests/edu_edges/` | 38 tests, 14 edges, mutation probes proving each test discriminates |
| Operator console | `claimguard/cli/` | `status`, `serve`, `evaluate`, `report` — each a real gate with meaningful exit codes |

**For scale:** the starter baseline the mentors shipped scores **0.43 F1** and 20% status accuracy,
because it implements three of the fifteen rules.

**Verified limits, stated up front:** the data is synthetic and the rulebook fictional; the labels
are an instructional oracle, not clinical or reimbursement ground truth; several rule edges cannot
be discriminated by the public labels at all (the mentor's 200 held-out claims are the real test);
a `PASS` is never payer approval; and CI green does **not** prove mentor-scorer conformance — that is
why `make edu-conformance` is a mandatory pre-submission step.

---

## Documentation

| # | Document | What it's for | Who reads it first |
|---|---|---|---|
| — | [`HANDOFF.md`](HANDOFF.md) | **Everything about this project in one file**: the graded contract, the timeline, the module map, what is verified, what is not, the traps, and how to run it all | **Anyone new — start here** |
| 01 | [`docs/01-DOMAIN-Gulf-Claims-101.md`](docs/01-DOMAIN-Gulf-Claims-101.md) | Gulf/Dubai claims metier from zero | **The 3 beginners — start here** |
| 02 | [`docs/02-PROBLEMATIC-Impact.md`](docs/02-PROBLEMATIC-Impact.md) | The problem + all sourced statistics | Everyone |
| 02B | [`docs/02B-PITCH-Problem-Narrative.md`](docs/02B-PITCH-Problem-Narrative.md) | Pitch-ready version of 02 | Deck authors |
| 03 | [`docs/03-Challenge-Decode-Requirements.md`](docs/03-Challenge-Decode-Requirements.md) | Challenge decode, scoring, traceability matrix | Head of project |
| 04 | [`docs/04-Architecture.md`](docs/04-Architecture.md) | Architecture v1, ADRs, tech choices | Head + Senior dev |
| 05 | [`docs/05-System-Design-Data-Model.md`](docs/05-System-Design-Data-Model.md) | Data model, DDL, rule syntax, benchmark design | Implementers |
| 06 | [`docs/06-Cahier-Des-Charges.md`](docs/06-Cahier-Des-Charges.md) | FR-001–105, NFR-001–020, UC-01–10 | Head + reviewers |
| 09 | [`docs/09-ARCHITECTURE-V2-Decisions.md`](docs/09-ARCHITECTURE-V2-Decisions.md) | Architecture v2 decisions, cut list, sprint plan | Head + Senior dev |
| 10 | [`docs/10-ADR-Starter-Pack-Authority.md`](docs/10-ADR-Starter-Pack-Authority.md) | **Which contract is graded**, and what it supersedes | **Whole team** |
| 11 | [`docs/11-Architecture-and-Dataflow.md`](docs/11-Architecture-and-Dataflow.md) | The pipeline as built, with trust boundaries and tool permissions | Reviewers |
| 12 | [`docs/12-Privacy-and-Security-Note.md`](docs/12-Privacy-and-Security-Note.md) | Safety posture, the untrusted-text rule, and what is **not** built | Reviewers |
| 13 | [`docs/13-Technical-Report.md`](docs/13-Technical-Report.md) | Implementation, decisions, tests, limitations | Jury |
| 14 | [`docs/14-Contribution-Log.md`](docs/14-Contribution-Log.md) | Roles and an honest statement of AI-tool use | Jury |
| 15 | [`docs/15-Demo-Script.md`](docs/15-Demo-Script.md) | The 7-minute demo, beat by beat, with a fallback | Presenters |
| 17 | [`docs/17-JEV-Judge-Layer.md`](docs/17-JEV-Judge-Layer.md) | Typed probabilistic second opinion, strict sidecar boundary and offline-safe operation | AI/ML + jury |
| 18 | [`docs/18-SLM-Benchmark-Methodology.md`](docs/18-SLM-Benchmark-Methodology.md) | Colab protocol, preserved Gemma 4/Phi-4 Mini/Qwen3 run and secured-contract v2 rerun plan; no checkpoint is deployable yet | AI/ML + jury |
| 19 | [`docs/19-Assistance-Security-Envelope.md`](docs/19-Assistance-Security-Envelope.md) | AegisGraph-inspired SLM authority graph, correction contract, verifier decisions and receipts | Security + jury |
| 20 | [`docs/20-Implementation-Completion-Report.md`](docs/20-Implementation-Completion-Report.md) | Complete release inventory, architecture, verification, limitations, remaining work and operational handoff | **Whole team + jury** |
| — | [`docs/verification/EDU-EVALUATION-REPORT.md`](docs/verification/EDU-EVALUATION-REPORT.md) | Generated evaluation report (single source for every metric) | Jury |
| — | [`docs/verification/EDU-PACK-CONFORMANCE.md`](docs/verification/EDU-PACK-CONFORMANCE.md) | How conformance is verified: oracle + independent second opinion | Reviewer |
| — | [`docs/verification/REPRODUCIBLE-SAMPLE-RUN.md`](docs/verification/REPRODUCIBLE-SAMPLE-RUN.md) | Captured end-to-end transcript | Reviewer |
| — | [`docs/verification/PHASE-1-GAP-ANALYSIS.md`](docs/verification/PHASE-1-GAP-ANALYSIS.md) | **What Phase 1 requires vs what we shipped**, gap by gap, with the remaining gaps and the plan to close them | Head of project |
| — | [`docs/verification/AUDIT-REPLAY.md`](docs/verification/AUDIT-REPLAY.md) | A stored run reconstructed from the ledger, with the chain verified | Auditor |
| — | [`docs/verification/FHIR-MAPPING-EXAMPLE.md`](docs/verification/FHIR-MAPPING-EXAMPLE.md) | One real bundle projected, and what FHIR cannot carry | Reviewer |
| — | [`docs/verification/AI-ABLATION.md`](docs/verification/AI-ABLATION.md) | What the assistance layer contributes, and what it costs when the model fails | Reviewer |
| — | [`docs/verification/ADVERSARIAL-CASES.md`](docs/verification/ADVERSARIAL-CASES.md) | 87 boundary cases against the rulebook's exact wording, and what they found | Reviewer |
| — | [`TEAM-ROADMAP.md`](TEAM-ROADMAP.md) | How we work: methodology, ground rules, milestones | **Whole team — start here** |
| — | [`TEAM-TASKS.md`](TEAM-TASKS.md) | Current sprint: one lab per person, with steps and a done-checklist | **B1, B2, B3** |

> Documents 07 and 08 (the original per-task plan and per-person sprint backlog) were retired when
> the mentor's labelled dataset arrived and are kept locally, not in the repository. Their successors
> are `docs/10` (the contract decision) and `TEAM-TASKS.md` (the current work).

---

## Core design decisions

1. **Deterministic core, AI at the edges.** Fifteen named, versioned rules decide every outcome. The
   explanation layer runs *after* the rules and may only rewrite prose — it cannot change a status, a
   severity, or a routing decision, and an output asserting a decision is rejected.
2. **A result for every check, not only for failures.** Each claim produces exactly fifteen records —
   `PASS`, `FAIL`, `UNABLE_TO_ASSESS`, `NOT_APPLICABLE` or `NOT_IMPLEMENTED` — because "I could not
   tell" and "the rule does not apply" are different facts, and neither is a pass.
3. **Evidence-first.** Every result carries `{path, value}` pointers into the *original* claim, and
   the mentor's scorer rejects the whole run if a value does not re-resolve. Bad input becomes a
   structured ingestion error; it is never a crash and never a silent pass.
4. **Confidence is not invented.** Deterministic checks report `confidence: null` with
   `confidence_kind: not_probabilistic`. Calibration is Phase 2 work and is not claimed here.
5. **Audit from birth.** Append-only Postgres with a SHA-256 hash chain, plus run-level metadata
   (input hash, rule/model/prompt versions). Tamper-*evident*, and we say so rather than claiming
   immutability we have not built.
6. **Review, don't adjudicate.** Never approves, denies, diagnoses, or advises treatment.
   Crossing the clinical boundary is a disqualifier, not a point loss.

---

## Team

Roles and the current per-person work are in [`TEAM-TASKS.md`](TEAM-TASKS.md) and
[`TEAM-ROADMAP.md`](TEAM-ROADMAP.md).

| Role | Focus |
|---|---|
| **HeadOfProject** | Architecture, the graded contract, review of all contributed work |
| **SeniorDev** | Engine, audit ledger, reviewer API and interface, CI |
| **B1 — Chatbot** | AI/language: explanation quality measurement |
| **B2 — Deep Learning** | Statistics: uncertainty, intervals, abstention analysis |
| **B3 — Computer Vision** | Documents and data integrity: attachments, FHIR gap verification |

---

## House rules

- **Every statistic carries (source, year, URL) — or it does not go on a slide.**
- Banned folklore: `$262B denied`, `65% never resubmitted`, `30% waste`, `MISBAR`. See `02 §3.7`.
- Synthetic data only. No real member records, ever.
- No merge to `main` without green CI and an approving review.
- No number in a report that was not produced by a command we can re-run.
- The demo must never be flaky, and a `PASS` is never described as approval.
