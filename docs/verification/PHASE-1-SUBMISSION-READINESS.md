# Phase 1 — submission readiness, 1 October 2026

## Decision

ClaimGuard has a substantial working MVP, not just a frontend prototype. Its strongest evidence is deterministic rule conformance, source-linked findings, persisted human review, immutable claim corrections, and a tamper-evident audit trail. Clinic tenancy and role-specific workflows go beyond the minimum Phase-1 surface.

**Do not describe the submission as fully complete yet.** The important remaining work is the recorded MVP video, a frozen/reproducible submission package, and honest evidence for the AI component. The supplied SLM experiment does not approve a model for deployment. FHIR ingestion is a documented partial educational projection, not a general FHIR integration.

This assessment supersedes `PHASE-1-GAP-ANALYSIS.md`; it does not erase the historical results in that document.

## Source and scope

The official **CSTAM-BOOK.pdf** was inspected visually, especially pages 17–19 and 25. It is locally supplied reference material, not redistributed here. The book has outlined text, so its empty text-extraction result was not used as evidence of missing requirements.

- Phase 1: MVP, **50 points**, due **1 October 2026**.
- Phase 2: integration/testing, 30 points, 20 October.
- Phase 3: UI/UX and documentation, 10 points, 1 November.
- Pitching belongs to the finals. **A pitch deck is not a Phase-1 blocker.**
- The mentor starter pack adds useful implementation/acceptance details; its proposed assessment weights are not the official rubric.

The scores below are the book's allocations, not a predicted jury score.

## Required versus implemented

| Official Phase-1 item | Points | Current evidence | Readiness and limits |
|---|---:|---|---|
| Ingestion and normalization of claim packages, including JSON/CSV and FHIR R4 data | 15 | `claimguard/edu/intake/`; Document Intake; `PHASE1-HANDS-ON-REHEARSAL.md` | JSON and five-file CSV now reach a persisted run through the UI. FHIR reaches the same engine **only with a verified full sidecar**: the Bundle recovers 30/41 envelope leaf paths, leaving 11 unsupported. Encounter is present in the sample Bundle but absent from the frozen internal scoring envelope. This item is still partial for FHIR-alone/general encounter normalization. |
| Deterministic and AI rule engine for a fictional payer, approximately 10–15 rules | 15 | All 15 rules R001–R015; `EDU-EVALUATION-REPORT.md`; bounded provider/verifier/fallback implementation | Deterministic path strongly evidenced. The committed evaluation reports 9,000/9,000 correct public labels over 600 claims. That is public-data conformance, not unseen-data accuracy. AI architecture is implemented, but approved-model evidence remains a gap. |
| Structured explanations: claim/rule identity, evidence, severity, confidence and corrective action | 10 | Frozen result schema; pointer verification; correction recommendations; per-finding provenance | Implemented. A deterministic `null` confidence is not a calibrated probability: explain the schema convention, never invent a certainty score. The interface distinguishes deterministic wording from accepted model wording. |
| Auditable history of checks, recommendations/confidence and decisions | 10 | Append-only PostgreSQL run/decision ledger, stored result and explanation rows, hash-chain trigger, immutable versions, `AUDIT-REPLAY.md` | Run-level and decision-level trail works and was integration-tested again; not every individual rule check, rejected intake or admin/UI action has its own chained event. Tamper-evident is not invulnerable to a database owner who can rewrite both data and verification roots. |

### Mandatory delivery artifacts

| Artifact | Present now | Still to do |
|---|---|---|
| Repository with installation/run instructions | README, lockfiles, environment example, migrations, startup/evaluation commands | Verify a clean checkout without private handoff, local credentials or an undocumented mentor-pack dependency; identify the exact submitted commit. |
| Architecture diagram and data-flow documentation | `docs/11-Architecture-and-Dataflow.md`; clinic additions in `docs/21-Clinic-Platform-Foundation.md` | Ensure the submitted diagram labels tenant boundary, deterministic engine, optional SLM/verifier/fallback, human correction/recheck, and audit persistence consistently. |
| Short MVP demonstration video | Existing script in `docs/15-Demo-Script.md`; improved UI available | **Record and export the actual video.** A script or screenshots are not the delivery artifact. |

## What works in the platform

- Clinic-scoped authentication and role checks; separate reviewer, lead, clinic-admin and technical-manager navigation.
- Reviewer queue, source-linked findings, decision notes, information requests and correction editor; corrections preserve the old run and rerun deterministic checks in a new version.
- Lead team queue, personal queue, assignments, escalations and review-quality reporting. Team Queue and My Queue have different scopes, not duplicate purposes.
- Clinic-admin overview, all claims, assignments, departments, team/access, analytics and audit.
- Technical-manager operational surfaces remain outside this redesign; technical access is not permission to inspect clinical claim contents.
- Structured intake with a human verification boundary. It is **not arbitrary PDF/image OCR**, and document intake is not a substitute for the full education-data CLI intake routes.
- Model provider integration, output verification, rejection provenance and safe deterministic fallback. These mechanisms work even when no model is enabled; that does not mean an SLM is currently providing every explanation.

## AI: the most important qualification

`slm-benchmark/2026-09-25/README.md` records the supplied Colab experiment: five configurations ran, every `safety_gate_pass` is false, Gemma 4 BF16 was skipped for memory, and the 22-row semantic-review sheet contains no completed `supported` labels. **There is no approved winner from that run.**

The review service defaults to deterministic mode in `claimguard/review/explanations.py`. Model use requires explicit mode, endpoint and model configuration. **Neither UI appearance nor safety-gate tests prove model quality**, and nothing below changes that.

### The interactive assistant, added 2026-10-01 — demonstrated, and bounded

An assistant now sits beside the findings: a reviewer clicks **Explain with AI** on a finding, reads a
real explanation of why that claim is flagged, and can then hold a conversation about it
(`docs/22-AI-Assistant-Design.md`, migration `0011`). It is the one place a model is *visibly* in the
product, so its evidence is stated here with the same honesty rules as everything else:

| Claim | Evidence | What is **not** claimed |
|---|---|---|
| A model drafted reviewer-facing text, live | Called the running server: opening a finding returned `verification=accepted`, `groq:qwen/qwen3.8-27b`, 1.5 s, with citations that re-resolved against the stored claim | That the wording is *good* by any measured standard. No assistant benchmark exists |
| The answer is verified, not trusted | The draft passes the SAME verifier as the graded explanation layer: exact key set, every cited pointer re-resolved, prohibited assertions, injection detection | That the verifier cannot be improved on; a novel injection phrasing remains possible (cost: a refused answer, not a wrong one) |
| It degrades to the deterministic answer | A live rate-limited call returned `verification=fallback` with the provider's own reason recorded, and the reviewer still received a complete deterministic explanation | That a fallback is a model answer. The interface labels it |
| It refuses what it must not do | "Should we just pay this claim?" → `verification=refused`, reason *"out of scope (decision_request); no model was asked"* — deterministically, before any model was reachable | That every out-of-scope phrasing is caught |
| It cannot change the graded record | Answers are stored in `claimguard.assistant_turns`, an append-only sidecar; no code path writes `rule_results`, `run_explanations` or the audit ledger | — |

**What leaves the machine, and the choice behind it.** When the assistant runs against a cloud model,
the finding, **the values of the evidence it cites** and the reviewer's question are sent to that
provider. Nothing else, and never a credential. The default is `CLAIMGUARD_AI_MODE=off`, in which
nothing leaves at all and the assistant still answers from the deterministic layer. Using a cloud
model is a deliberate, temporary deployment decision: the design is a self-hosted or fine-tuned
checkpoint, and the mode switch is what makes that a configuration change rather than a rewrite.

Before claiming a successful AI demonstration:

1. Complete human support/entailment judgments on model outputs, including correction recommendations and abstentions.
2. Diagnose the recorded failures. Separate schema, citation, unsafe recommendation and task-quality failures; do not loosen safety rules simply to obtain a winner.
3. Evaluate any prompt/schema or fine-tuning change on a held-out set with the same baseline. Fine-tuning is an experiment, not an automatic requirement or guarantee.
4. Capture a real accepted model output, its evidence citations and provenance, plus a rejected output/fallback example, without changing the deterministic status.
5. If no candidate qualifies before submission, disclose the deterministic deployment and the bounded-model integration honestly. Ask the mentor how this affects the AI requirement; do not claim all 15 engine points are secured.

## Changes in this frontend iteration

The layout is inspired by the public [Adminator dashboard](https://github.com/puikinsh/Adminator-admin-dashboard) screenshots: light sidebar, restrained topbar, generous panel spacing, clear metrics and practical tables. It is an original Next.js implementation using ClaimGuard's existing navy/blue/aqua identity and installed component primitives; no Adminator template assets or code were copied.

- `/` is now a product landing page: explanation of the workflow, team roles, safety boundaries and working workspace links. The claim illustration is explicitly labelled, with no invented customer logos, adoption numbers or payer-approval promises.
- `/workspace/home` opens the signed-in role's home or the clinic sign-in screen.
- Business navigation has persistent collapse preference, mobile open/close controls and breadcrumbs.
- Admin Overview and Analytics read `/v1/analytics`. Counts/charts represent recorded clinic data, not randomized demonstration numbers. Pending intake and request counts identify RCM ownership instead of linking to unrelated work.
- RCM/all-claims surfaces retain the real correction/recheck and decision APIs. Search and review-state filters refine the loaded queue; they are not server-wide analytics filters.
- Business activity, audit and review-quality tables gain search, sorting, pagination and expandable structured details; identifiers remain exact.
- Technical-manager pages, API contracts and database schema were not redesigned or migrated by this iteration.

## Verification evidence for this iteration

Fresh checks, 1 October 2026:

- Focused Python regression command: `PYTHONUTF8=1 python -m pytest tests/edu tests/edu_intake tests/edu_explain tests/edu_edges tests/review/test_audit_replay.py -q` — **344 passed**. On Windows PowerShell, set `$env:PYTHONUTF8='1'` before running. Without it, Unicode subprocess transcripts failed decoding; the UTF-8 rerun succeeded. This is not a new full PostgreSQL integration-suite run.
- Frontend checks and browser outcomes are recorded in `FRONTEND-PRODUCT-REFRESH.md`.
- Previously captured 600-claim conformance and audit-trigger reports remain historical artifacts, not newly remeasured model/generalization results.

## Remaining work, ordered for first submission

1. **Submission delivery:** confirm upload instructions and deadline, choose the exact commit, record/export the short MVP video, and package the repository plus architecture/data-flow notes. The book's due date is today; do not let optional features displace delivery.
2. **AI evidence and disclosure:** finish the limited accepted-output/fallback demonstration and describe the benchmark gate honestly. If unresolved, flag it explicitly rather than deploying a rejected candidate.
3. **Clean-run rehearsal:** follow README on a clean environment; run migrations, seed only synthetic demo data, sign in for each role, and exercise intake → assignment → reviewer decision → correction/recheck → audit. Keep credentials out of Git and the public video.
4. **Align documentation:** state FHIR limitations, confidence semantics, public/held-out evaluation separation and exact model mode in the submitted report. The mentor's 200 held-out claims are not available locally.

### Suggested short video sequence

Landing/value proposition → admin overview and assignment → reviewer queue → rule and source evidence → guidance provenance → documented correction and new-version recheck → audit/history. Briefly show role/tenant separation. Use only synthetic records and do not expose account passwords, private handoff notes or API keys. Demonstrate model wording only if the run actually used an accepted model response.

## Later phases — valuable, not reasons to miss Phase 1

- Phase 2: mentor-held evaluation, real semantic AI evaluation, explicit correction-success metrics, tenancy/security and concurrency tests, deployment monitoring, candidate fine-tuning if measured weaknesses justify it.
- Phase 2/3: synthetic dental-document extraction proof of concept, field-level provenance and human verification before claim generation, with adversarial and missing-document tests. OCR/document-assisted creation is an enhancement, not already shipped general intake.
- Phase 3: deeper usability testing with reviewers/admins, keyboard/focus audit, cross-browser/responsive testing, performance and accessibility measurement, cohesive final report/demo.
- JEV: evaluate a narrowly bounded advisory location with latency, quality, failure and privacy measurements before integrating. Do not place it in charge of deterministic pass/fail, claim correction, eligibility adjudication or submission. It is not a prerequisite in the Phase-1 rubric.

This document contains no local credentials or private handoff material.
