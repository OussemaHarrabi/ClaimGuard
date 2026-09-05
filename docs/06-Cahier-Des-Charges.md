# 06 — Cahier des Charges (Formal Specification)

> **Document:** The contractual specification for ClaimGuard AI — what the system must do, formally, with numbered, prioritized, testable requirements.
> **Project:** ClaimGuard AI — CSTAM-VELODOC Challenge ("Trustworthy Agentic Copilot for Healthcare Claim Pre-Validation")
> **Audience:** Jury, Velodoc client, team (incl. 3 beginners), mentors.
> **Status:** v1.0 · 2026-09-04 · For registration submission (5 Sept 2026) and Phase-3 selection gate (1 Nov 2026).
> **Companion docs:** `01-DOMAIN-Gulf-Claims-101.md` (domain), `02-PROBLEMATIC-Impact.md` (problem & market), `03-Challenge-Decode-Requirements.md` (challenge decode & traceability), `04-Architecture.md` (architecture & ADRs), `05-System-Design-Data-Model.md` (data model, DDL, rule YAML, API, benchmark).
> **Conventions:** Every requirement is numbered (`FR-xxx`, `NFR-xxx`, `UC-xx`) and testable. Priorities use MoSCoW: **MUST** (contractual — without it the phase fails), **SHOULD** (important, defer only with justification), **COULD** (nice-to-have), **WON'T** (explicitly excluded). Every FR maps to a scored component of the challenge. No statistic is invented: market figures live in `02` §3 with sources; values marked "cible projet" (project target) are engineering targets we set and measure ourselves.

---

## 1. Objet du cahier des charges — Purpose

This document is the **formal specification** of ClaimGuard AI. It binds the team as supplier to the challenge jury and to Velodoc as client. It defines:

1. **What the system must do** — the functional scope, expressed as numbered requirements with acceptance criteria;
2. **How well it must do it** — measurable non-functional targets;
3. **What it must never do** — the clinical and adjudicative boundary;
4. **What will be delivered, when** — the phased deliverables and recette (acceptance) plan.

**Who it binds.** The five team members (project lead, senior engineer, three beginners), each of whom accepts the requirements in their area of work. It does **not** bind Velodoc to any obligation beyond the published challenge rules; it *is* the team's own contract with itself, so the jury can hold us to it.

**Scope of the document.** Functional & non-functional requirements (sections 5–6), constraints (7), detailed use cases (8), interface specification (9), acceptance / recette plan (10), deliverables (11), and macro planning (12). Detailed architecture decisions are in `04`; the data model and rule syntax are in `05`. This document is the *what*; `04`/`05` are the *how*.

**Vocabulary.** Used exactly as in `01` §0: **payer, reviewer, signal, finding, claim package, quality gate, synthetic fixtures, "review, don't adjudicate", copilot, handoff**.

---

## 2. Presentation du projet — Project in one page

**The problem.** When a Dubai clinic submits a claim to a payer, the claim is a stack of administrative paperwork — member identity, coverage, authorization, codes, charges, attachments — assembled by humans under time pressure and frequently wrong in small, fixable ways (a coverage that lapsed, a missing authorization, a duplicated line). The payer detects these problems **after** submission, and the provider only learns of them weeks later, entering a slow rework-and-appeal loop. The problem, its cost, and the current market are documented with sources in `02` (§3).

**The solution.** ClaimGuard AI is a **pre-submission quality gate**: a copilot that reads the complete **claim package** the moment it is assembled — before it crosses to the payer — and produces **signals and findings**: structured, explainable problem reports with a rule ID, evidence, severity, and confidence, handed to a human reviewer who decides. **Review, don't adjudicate.**

**The intervention point.** ClaimGuard sits at the last moment before submission — after claim build, before the payer/TPA — and moves the *discovery* of claim problems from after-submission (where every error costs a denial cycle) to before-submission (where fixing is cheap). This positioning is detailed in `02` §9.

**The value proposition.**
- **For the provider's billing staff (our user):** fewer denials, fewer rework cycles, faster cash flow, a defensible submission trail (courtesy of the audit log).
- **For the payer (Velodoc's world):** cleaner inbound claims, fewer front-door rejections, less manual review.
- **For the jury:** a **trustworthy** agentic system — deterministic where it must be, LLM only where it is safe, calibrated confidence, a full audit chain, and a demonstrated "knows when to ask for help" behavior — engineered to stay inside the administrative lane.

**The architecture shape (fixed — see `04`).** Pipeline **Ingest → Normalize → Validate → Handoff** (matching Velodoc's Claim Lab phases): a deterministic, enum-driven Python core with **rules as data** (versioned YAML/JSON manifests evaluated in CEL); LLM permitted **only** at the edges (normalization of free text, explanation narratives, attachment classification); every finding cites provable JSON-Pointer evidence; confidence is calibrated with conformal abstention (α = 0.05) and all abstentions route to human review; a three-tier HITL with mandated escalations that are never confidence-gated; an append-only, hash-chained audit log with OpenTelemetry tracing. Nothing in this pipeline adjudicates, diagnoses, or recommends treatment.

---

## 3. Perimetre fonctionnel — Scope

### 3.1 In scope

- Pre-submission validation of **synthetic** claim packages in **FHIR R4 JSON** and **CSV**;
- Claim **package** validation: claim data + attachments + authorization references + encounter references;
- Detection of the six **signal families**: Coverage, Authorization, Integrity, Identity, Documentation, Clean;
- Deterministic rule engine over a versioned, rules-as-data catalogue (Velodoc fixture rules COV-001 … ENV-001, mapped onto the published R01–R15 catalogue);
- LLM-assisted normalization of free text/OCR into canonical fields, human-readable explanation narratives, and attachment classification — **never** rule outcomes;
- Calibrated confidence with conformal abstention and HITL routing;
- Three-tier human review with structured, reason-coded overrides;
- Append-only audit log with SHA-256 hash chain, replayability, and OpenTelemetry traces;
- Rule catalogue management (API + GUI), evaluation harness and benchmark reports, reviewer UI;
- Docker Compose deployment with an offline-capable, local/open-weights LLM option;
- Bonus scope if pursued: OCR/RAG attachment parsing, dynamic payer-rule GUI/API, active learning from overrides, cryptographic audit log, real-time streaming REST/WebSocket API.

### 3.2 Out of scope (explicitly)

| # | Excluded | Why | Reference |
|---|---|---|---|
| 1 | **Real payer integration** (EDI 837/835, eClaimLink, payer APIs) | Synthetic-only challenge; no production connectivity | Règle challenge |
| 2 | **Real EMR/EHR integration** | No real clinical systems; inputs are files | Règle challenge |
| 3 | **Production PHI** (real patient data) | Challenge rule; we de-identify and guard | Règle challenge; FR-066 |
| 4 | **Adjudication** (deciding paid/reduced/denied) | Core principle: review, don't adjudicate | FR-064 |
| 5 | **Clinical decision support** (diagnosis, treatment recommendation, medical necessity judgment) | Regulatory boundary (FDA CDS, EU AI Act) — see §7.2 | FR-062 |
| 6 | **Payment processing** (claims submission, remittance handling) | Would move us across the gate; out of the quality-gate lane | §2 |
| 7 | **Multi-tenant SaaS** (real customer onboarding, billing, SLAs) | Challenge horizon; single-deployment product | NFR-006, NFR-011 |
| 8 | **Mobile app** | WON'T unless taken as a bonus — desktop-web UI only | FR-105 |

Any work pushing into these lanes is a scope violation and must be rejected by the project lead.

---

## 4. Acteurs et roles — Actors & Roles

| Actor | Who | May do | Must not do |
|---|---|---|---|
| **Provider / billing staff** (user of the output) | The reviewer-side user of the quality gate | Upload claim packages; read findings; act on suggested corrective actions; submit corrected packages for re-validation | Bypass the quality gate; ignore mandatory escalations without review; alter audit data |
| **Reviewer T1** | First-line billing staff | Review routine findings (Low/Medium), confirm or dismiss with a reason code, correct data and re-run | Override High-severity or mandated-topic findings alone |
| **Reviewer T2** | Senior billing/claims specialist | Review High-severity findings; handle all mandatory-topic escalations; perform reasoned overrides with a reason code | Override without a reason code; override when evidence contradicts |
| **Reviewer T3 / supervisor** | Team lead / auditor role | Final authority on policy-level overrides; review override history; reopen reviews | Modify the audit log, rule internals, or reason-code enums without trace |
| **Administrator** | Trusted team member | Manage rule catalogue (add/modify/version rules), manage users and roles (RBAC), run evaluations, monitor system health | Edit rules that are hash-pinned to a published claim; grant self-override rights |
| **Auditor** | External or internal reviewer of the system itself | Read the audit log; verify hash-chain integrity; replay any historical decision; export audit evidence | Modify the audit log (append-only enforced in DB) |
| **System** | ClaimGuard pipeline | Ingest → normalize → validate → handoff; emit findings; route to HITL; write audit entries; stop safely on ENV-001 | Adjudicate, diagnose, recommend treatment, override rule outcomes, edit the canonical package after it is sealed, block on audit failure (fail open) |

---

## 5. Exigences fonctionnelles — Functional Requirements

### 5.A Ingestion & normalization (Phase 1 — Ingestion & normalization: 15 pts)

#### FR-001 — FHIR R4 JSON intake — **MUST** · Score: Phase 1 (15)
**Description:** The system accepts a claim package expressed as FHIR R4 JSON (one or more bundles: Claim, Patient, Coverage, Encounter, RelatedPerson/practitioner, DocumentReference for attachments, and an envelope/submission header).
**Acceptance (checkable):** Given a valid FHIR R4 JSON package, When submitted via API or UI, Then it is parsed without error into the canonical claim package and a `202`/`200` with a package ID is returned; given a syntactically invalid JSON, when submitted, then a structured error (not a stack trace) is returned and no claim is created.

#### FR-002 — CSV intake — **MUST** · Score: Phase 1 (15)
**Description:** The system accepts a flat CSV (claim-line oriented) mirroring the canonical fields, with a documented column contract (see `05`), and normalizes it to the same canonical model as the FHIR path.
**Acceptance (checkable):** Given a valid CSV file conforming to the published column contract, when ingested, the resulting canonical package is field-equivalent to the same data submitted as FHIR; given a CSV with unknown columns or type mismatches, a structured validation error per row is produced.

#### FR-003 — Bundle reference resolution — **MUST** · Score: Phase 1 (15)
**Description:** All internal references within the FHIR bundle (e.g., `Claim.patient` → `Patient.id`, `Claim.item.revenue` → line, `DocumentReference` → attachment blob) are resolved; the canonical package stores **resolved** references as JSON Pointers (RFC 6901).
**Acceptance (checkable):** Given a bundle with internal references, when ingested, every reference used by any rule resolves to a concrete node in the canonical package (verified in code at validation time); given a dangling reference, the package is routed to normalization error handling (FR-004) with a precise pointer to the missing node.

#### FR-004 — Malformed / incomplete envelope handling (ENV-001) — **MUST** · Score: Phase 1 (15) + Documentation family
**Description:** The pipeline performs an early envelope check (ENV-001: minimum claim envelope — submitter, member, provider, service date, at least one line). On ENV-001 failure the pipeline **stops safely**: no LLM call, no downstream rules, a finding is emitted, and the package is routed to the reviewer queue. Never a crash.
**Acceptance (G/W/T):** Given a package missing a member identifier, when submitted, Then the pipeline halts before any LLM invocation, an ENV-001 finding (High) is written, the package lands in the review queue with status `ENVELOPE_INCOMPLETE`, and the API returns a normal (non-500) result.

#### FR-005 — Canonical claim package — **MUST** · Score: Phase 1 (15) + Phase 1 explainability (10)
**Description:** All inputs produce one canonical, sealed package (Pydantic models — see `05`): stable IDs, normalized dates/codes (canonical format), resolved pointers, and a hash. The package is **immutable after validation starts**; the LLM never edits it.
**Acceptance (checkable):** Given any input, when ingested, the canonical package is produced with a package hash; a hash check after validation confirms no mutation; the normalized representation is identical for semantically identical FHIR and CSV inputs.

#### FR-006 — LLM-assisted normalization of free text — **SHOULD** · Score: Phase 1 (15) + Phase 2 HITL (10)
**Description:** Where input fields are free text or noisy OCR (e.g., diagnosis description → code, provider name → canonical provider), the LLM **may** propose canonical values with a confidence score. This is the only place LLM output becomes part of the canonical package, and it is validated by Pydantic structured output with bounded retry (FR-021).
**Acceptance (G/W/T):** Given a free-text diagnosis field, when normalization runs, Then the output is a structured canonical value with schema validation passing on the first or a bounded retry; given repeated schema failure after max retries, the field is marked `LLM_UNRELIABLE` and routed to HITL (FR-042).

#### FR-007 — Normalization confidence & routing — **SHOULD** · Score: Phase 2 HITL (10)
**Description:** Normalization outputs below the conformal abstention threshold (FR-033) never silently enter the package; they route to HITL with the raw text and the LLM's candidate alongside the deterministic evidence.
**Acceptance (checkable):** Given a normalization output below threshold, when validation proceeds, the finding set includes a normalization-review task; no low-confidence canonical value is used by any rule without human confirmation.

#### FR-008 — Synthetic-data-only guard — **MUST** · Score: Phase 2 privacy/security/safety (5)
**Description:** The repo, fixtures, and demos contain only synthetic data. A pre-commit/lint-time check flags known real-world identifier patterns and any labeled `REAL` data source; the ingest path warns (and, in demo mode, refuses) when a payload resembles real PHI (e.g., valid Emirates ID patterns outside the fixture set are flagged for review).
**Acceptance (checkable):** Given a repository scan, when run in CI, zero files contain real patient identifiers; given a synthetic-fixture payload, the guard passes it; given a payload with a realistic but non-fixture Emirates ID, the ingest layer flags it for human confirmation.

### 5.B Deterministic rule engine & rule catalogue (Phase 1 — Deterministic + AI rule engine: 15 pts)

> **v2 note (2026-09-05) — fixture family authority hierarchy:** for the **12
> fixture-backed rules** (COV-001, COV-008, AUTH-004, AUTH-006, AUTH-009,
> DUP-002, INT-003, ID-002, ID-005, DOC-004, ENC-001, ENV-001) the **published
> Velodoc fixture label wins over the YAML manifest** — the fixtures are the
> only externally-published, externally-graded labels we possess. This corrects
> two rules in the FR-013 table and elsewhere: **ENC-001 = Identity** (was
> Documentation) and **ENV-001 = Documentation** (was Clean). The YAML manifest
> remains the single source of truth only for rules with no fixture (our ADDED
> rules PYR-001, AMT-001, ST-001, CLEAN-001, ID-001, LOC-001 and catalogue
> rules R03, R04 — unchanged). FR-004 and UC-06 are aligned to the same
> labels.

#### FR-010 — Rules as data — **MUST** · Score: Phase 1 (15) + NFR-010
**Description:** Every rule is a declarative manifest (YAML/JSON — schema in `05`): `rule_id`, `family`, `name`, `description`, `severity`, `condition` (CEL expression), `evidence_pointers`, `suggested_corrective_action`, `version`, `effective_from/to`. The engine is a small deterministic Python evaluator over the canonical package; adding a rule never requires core-code changes.
**Acceptance (checkable):** Given a new rule manifest added to the catalogue, when the engine runs, the rule is evaluated without any code change; given a malformed manifest, a manifest-validation error is raised at load time with the offending field.

#### FR-011 — Rule versioning & hash pinning — **MUST** · Score: Phase 1 (15) + audit credibility
**Description:** Rules carry semver + effective dates; the catalogue is hash-pinned in git; a claim records which catalogue version (hash) validated it.
**Acceptance (checkable):** Given two catalogue versions, the same claim validated under each produces findings annotated with the respective version/hash; the audit log for a claim stores the exact catalogue hash used.

#### FR-012 — CEL condition evaluation — **MUST** · Score: Phase 1 (15)
**Description:** Computable rule conditions are evaluated with CEL (via `cel-python`) against the canonical package; evaluation is pure (no side effects), timeboxed per rule, and sandboxed to the package data.
**Acceptance (checkable):** Given a rule with a CEL condition, when evaluated, the boolean result matches the documented semantics on fixture and mutation cases; given an evaluation error or timeout, the rule is reported as `RULE_EVAL_ERROR` (an operational finding, not a claim finding) and the pipeline continues (fail-open per rule, never false-positive on error).

#### FR-013 — Full fixture rule set — **MUST** · Score: Phase 1 (15); verified on CLM-0042
**Description:** The catalogue implements Velodoc's 12 fixture rules, mapped onto the published R01–R15 catalogue (veloclaim.app/reference) by family. Delivery is verified on the 13 synthetic fixtures, including flagship **CLM-0042** (Sara Mansour).

| Rule ID | Family | Fires when… | Severity | Fixture proof |
|---|---|---|---|---|
| COV-001 | Coverage | Coverage inactive on date of service | High | CLM-0042 signal (conf. 0.99) |
| COV-008 | Coverage | Benefit balance likely exhausted | Medium–High | Dental-limit example |
| AUTH-004 | Authorization | Required approval missing | High | CLM-0042 signal (conf. 0.96) |
| AUTH-006 | Authorization | Approval invalid on service date | High | Expired-auth example |
| AUTH-009 | Authorization | Referral does not match billed service | High | CT-vs-MRI example |
| DUP-002 | Integrity | Duplicate service line | Medium | CLM-0042 signal (conf. 0.88) |
| INT-003 | Integrity | Service periods overlap | Medium | §1 example C set |
| ID-002 | Identity | Member/provider identity unresolvable | Medium | Envelope errors |
| ID-005 | Identity | Provider identifier missing | Medium | Claim build errors |
| DOC-004 | Documentation | Referenced attachment not uploaded | Medium | Missing-radiology-report case |
| ENC-001 | Identity | Encounter reference unresolvable/missing | High (mandated escalation) | Missing encounter |
| ENV-001 | Documentation | Minimum claim envelope incomplete | High (pipeline stop) | FR-004 |

**Acceptance (checkable):** Given the 13 synthetic fixtures, when validated, each fixture's expected rule fires with the expected severity and, for the flagship, confidence > 0.85; the R01–R15 mapping is documented per rule in `05`.

#### FR-014 — Severity assignment — **MUST** · Score: Phase 1 (15) + explainability (10)
**Description:** Severity is a first-class property of each finding (High/Medium/Low), defined by the rule manifest, not by the LLM.
**Acceptance (checkable):** Given any finding, the severity equals the manifest value; automated tests assert the severity of every rule in the catalogue.

#### FR-015 — Evidence-first findings (JSON Pointers) — **MUST** · Score: Phase 1 explainability (10)
**Description:** Each finding cites evidence as JSON Pointers into the canonical package (e.g., `/Coverage/period/end`). Pointers are resolved and verified **in code**; a finding whose evidence pointer cannot be resolved is not emitted (logged as a rule-authoring error).
**Acceptance (checkable):** Given any emitted finding, 100% of its evidence pointers resolve to existing nodes in the sealed package (enforced in the engine); given a rule with a dangling pointer in its manifest, the rule is rejected at load time.

#### FR-016 — Deterministic confidence — **MUST** · Score: Phase 1 (15)
**Description:** Deterministic rule outcomes carry confidence **1.0 by definition**; confidence scaling applies only to LLM-produced components (FR-030…FR-035).
**Acceptance (checkable):** Given any rule outcome, the recorded confidence equals 1.0 and is derived from the deterministic path alone; no calibration step alters rule confidence.

#### FR-017 — Finding output contract — **MUST** · Score: Phase 1 explainability (10)
**Description:** Every finding carries: **Claim ID, Rule ID, rule-linked evidence (resolving pointers), severity, confidence, suggested corrective action** — exactly the Phase-1 scored fields — plus family, catalogue version/hash, and timestamp.
**Acceptance (checkable):** Given any emitted finding, all six scored fields are present, non-empty, and schema-valid; the API response and UI render them without transformation loss.

#### FR-018 — LLM never decides rule outcomes — **MUST** · Score: Phase 1 (15) + trustworthiness
**Description:** The LLM has no path to influence rule results: rule evaluation is a pure deterministic function of the canonical package; LLM output is consumed only by FR-006/FR-020/FR-023 and validated post-hoc (cross-check that any cited rule_id is in the actually-fired set).
**Acceptance (checkable):** Given a claim where the LLM "disagrees" with a deterministic firing, the finding set is unchanged; a code-level cross-check rejects any narrative that cites a rule_id not in the fired set (FR-022).

#### FR-019 — Rule dry-run / what-if — **COULD** · Score: Phase 1 (15) bonus polish
**Description:** Administrator can run the catalogue against a package in "dry-run" to preview findings without writing audit entries, and can propose a rule change and see its effect on the fixture set before publishing.
**Acceptance (G/W/T):** Given a published claim package, when an admin dry-runs a modified catalogue, Then a preview of findings is shown with no audit entry written and no effect on stored claims.

### 5.C LLM enrichment & explanation (Phase 1 — Explainability & structured output: 10 pts)

#### FR-020 — Human-readable explanation narrative — **MUST** · Score: Phase 1 explainability (10)
**Description:** After deterministic rules fire, the LLM writes the reviewer-facing explanation: a concise natural-language summary of each finding (what is wrong, what evidence shows it, what to check), grounded in the fired rules. The narrative never overrides or adds findings.
**Acceptance (checkable):** Given a claim with findings, the narrative covers every fired rule and no others; each narrative sentence can be attributed to ≥ 1 evidence pointer or rule fact (FR-022 enforcement); the narrative is written only after rule evaluation completes.

#### FR-021 — Structured output with bounded retry — **MUST** · Score: Phase 1 explainability (10)
**Description:** All LLM output is Pydantic-structured (provider structured-outputs/JSON-schema mode), with **max 2–3 validate-and-retry attempts**; persistent failure produces an `LLM_UNRELIABLE` finding and routes to HITL. Syntactic-not-semantic caveat is enforced in code.
**Acceptance (G/W/T):** Given an LLM response failing schema validation, when retried up to the bound, Then a valid structure is used or, after the bound, `LLM_UNRELIABLE` is emitted and the item routes to HITL; given a syntactically valid but semantically wrong response (wrong rule_id), the post-hoc cross-check (FR-018/FR-022) catches it.

#### FR-022 — Citation grounding of explanations — **MUST** · Score: Phase 1 explainability (10)
**Description:** Every narrative claim must cite a resolving evidence pointer or a fired rule_id; verification is done in code: narrative citations that do not resolve are removed/flagged and the reviewer is told the narrative is partially ungrounded.
**Acceptance (checkable):** Given any narrative, 100% of its citations resolve; a test corpus of adversarial prompts (asking the LLM to cite nonexistent rules) yields zero accepted ungrounded citations.

#### FR-023 — Attachment classification (LLM) — **SHOULD** · Score: Phase 1 (15) + Bonus OCR/RAG (+2)
**Description:** The LLM may classify attachment kinds (e.g., referral letter, prior-auth approval, imaging report) from parsed text/OCR to support DOC-004/ENC-001 evidence. Classifications are advisory (human-visible), not authoritative.
**Acceptance (checkable):** On fixture attachments, classification accuracy ≥ 90% on a labeled subset; a classification is never used as sole evidence for a decision (always paired with deterministic package facts).

#### FR-024 — LLM_UNRELIABLE handling — **MUST** · Score: Phase 2 HITL (10)
**Description:** `LLM_UNRELIABLE` items are first-class review tasks with the raw input, the failed attempts, and the schema error summaries — never silent fallbacks.
**Acceptance (checkable):** Given an LLM failure, an `LLM_UNRELIABLE` task exists in the queue with diagnostics; the claim is not blocked from deterministic validation.

### 5.D Confidence & calibration (Phase 2 — Detection quality: 15 pts)

#### FR-030 — Self-consistency sampling — **MUST** · Score: Phase 2 (15)
**Description:** LLM-confidence components sample K=3 independent generations; agreement across samples feeds uncertainty estimation.
**Acceptance (checkable):** Given a normalization/explanation task, exactly 3 samples are drawn with distinct temperature/seed policy (documented); outputs and pairwise agreement are recorded for the confidence model.

#### FR-031 — Semantic entropy — **MUST** · Score: Phase 2 (15)
**Description:** Semantic entropy over the sampled outputs is computed (clustering by semantic equivalence, then entropy); it is a feature in the confidence model.
**Acceptance (checkable):** Given samples that are paraphrases, semantic entropy is near-zero; given diverging samples, entropy is high; unit tests assert both directions.

#### FR-032 — Calibration (Platt/isotonic) — **MUST** · Score: Phase 2 (15)
**Description:** Confidence scores are calibrated on a held-out set (Platt or isotonic regression, chosen by cross-validated log-loss); calibration is re-fit per model/catalogue change and versioned.
**Acceptance (checkable):** Given the held-out set, post-calibration ECE improves over the raw logprob baseline; the calibration object (parameters + data hash) is versioned and stored for audit replay.

#### FR-033 — Conformal abstention — **MUST** · Score: Phase 2 (15)
**Description:** A conformal abstention threshold at α = 0.05 decides when LLM-produced values are too uncertain to use; below threshold → HITL (never silent acceptance).
**Acceptance (checkable):** On the held-out set, the empirical coverage of non-abstained outputs ≥ 0.95 with the configured threshold; every abstained item produces a review task.

#### FR-034 — ECE & AUROC reporting — **MUST** · Score: Phase 2 (15) + differentiator
**Description:** The evaluation harness reports Expected Calibration Error (ECE) and AUROC alongside Macro F1 for every run — most teams never do; we always do.
**Acceptance (checkable):** Given a benchmark run, the report contains ECE and AUROC with the dataset and model version stated; values are reproducible on re-run with pinned versions.

#### FR-035 — Confidence scope discipline — **MUST** · Score: Phase 2 (15)
**Description:** The calibrated-confidence machinery is scoped to normalization (FR-006) and explanation (FR-020) only; deterministic findings keep confidence 1.0 (FR-016).
**Acceptance (checkable):** The confidence pipeline is invoked only from LLM-producing modules; architecture tests enforce the import boundary.

#### FR-036 — Active learning from human overrides — **COULD (Bonus +2)** · Score: Bonus
**Description:** Structured overrides (FR-043) feed a labeled dataset that is used to (a) propose threshold/calibration updates and (b) suggest new rules or condition refinements; all updates are admin-approved and versioned.
**Acceptance (G/W/T):** Given 20+ overrides with reason codes, when the learning job runs, Then it produces a candidate list (rule suggestions, threshold deltas) with expected impact on Macro F1; nothing is applied without admin approval.

### 5.E Human-in-the-loop routing & review (Phase 2 — HITL & escalation: 10 pts)

#### FR-040 — Three-tier routing — **MUST** · Score: Phase 2 HITL (10)
**Description:** Findings route by tier: **Tier 1** — routine (Low/Medium severity, high confidence); **Tier 2** — High severity or any mandated-topic finding; **Tier 3** — policy-level exceptions, override disputes, and auditor-flagged items. Tiers are a routing policy, configurable as data.
**Acceptance (checkable):** Given a finding set, the routing policy maps each finding to exactly one tier; the flagship CLM-0042 routes its COV-001/AUTH-004 (High) findings to ≥ Tier 2 and DUP-002 (Medium) to ≥ Tier 1.

#### FR-041 — Mandatory escalation never confidence-gated — **MUST** · Score: Phase 2 HITL (10)
**Description:** Findings involving **AUTH-004, AUTH-006, AUTH-009, ENC-001**, or **eligibility/benefit** topics escalate to human review regardless of confidence — priority: 0.99- or 0.10-confidence, they go to a human.
**Acceptance (checkable):** Given any claim where a mandated topic fires at any confidence, a human review task exists in the queue with no confidence-based bypass; the routing engine unit-tests this for the full mandated set.

#### FR-042 — Abstention → HITL — **MUST** · Score: Phase 2 HITL (10)
**Description:** Every conformal abstention (FR-033), LLM_UNRELIABLE (FR-024), or normalization uncertainty (FR-007) produces a human task; nothing is silently dropped.
**Acceptance (checkable):** Given a run with M abstentions/LLM failures, the queue contains ≥ M human tasks referencing them.

#### FR-043 — Structured overrides with reason codes — **MUST** · Score: Phase 2 HITL (10)
**Description:** A review decision is a structured record: `finding_id`, `decision ∈ {CONFIRM, CORRECT, DISMISS_WITH_REASON, ESCALATE}`, a **reason code from a fixed enum** (e.g., `DATA_FIXED`, `DOCUMENTATION_SUPPLIED`, `POLICY_EXCEPTION`, `DUPLICATE_INTENTIONAL`, `NOT_APPLICABLE`, `NEEDS_PAYER_INPUT`), optional corrective action, reviewer ID, timestamp. Free text is allowed only as supplementary notes, never as the sole justification.
**Acceptance (checkable):** Given a review action, the audit record contains a valid enum reason code; UI enforces enum selection before submission; statistics over reason codes are exportable (feeds FR-036).

#### FR-044 — Reviewer queue management — **MUST** · Score: Phase 2 HITL (10) + Phase 3 UI (10)
**Description:** A reviewer sees a prioritized queue (mandated topics first, then severity, then queue time), with filters by family, tier, and status; workloads are per-user with no cross-user silent reassignment.
**Acceptance (G/W/T):** Given a populated queue, when a reviewer filters by family=Authorization, Then only Authorization-family tasks are shown; mandated topics sort above non-mandated regardless of age.

#### FR-045 — Re-review after correction — **MUST** · Score: Phase 2 HITL (10)
**Description:** When a reviewer corrects data (e.g., adds the authorization number), the package is re-validated as a new versioned run; results are diffed against the previous run in the UI; the correction itself is part of the audit trail.
**Acceptance (G/W/T):** Given a corrected package re-submitted, when validation completes, Then the UI shows a before/after diff of findings; the audit chain links run N and run N+1.

#### FR-046 — Demo-mode sealed workflows — **SHOULD** · Score: Phase 3 UI (10) + demo quality
**Description:** A demo script (the 13 fixtures in fixed order) drives intake → findings → HITL → override → audit replay end-to-end without flakiness, with all LLM calls reproducible (pinned seeds/models or recorded cassettes).
**Acceptance (checkable):** Running `demo --fixture CLM-0042` produces the documented three findings (COV-001 0.99, AUTH-004 0.96, DUP-002 0.88) with a completed review and a verifiable audit chain, twice in a row identically.

### 5.F Audit & traceability (Phase 1 — Audit log engine: 10 pts; Bonus crypto audit log: +2)

#### FR-050 — Append-only audit log — **MUST** · Score: Phase 1 audit (10)
**Description:** Every meaningful event (ingest, normalization, each rule evaluation batch, each finding, routing, review decision, override, catalogue change) is written to an append-only Postgres table; the DB role grants **SELECT + INSERT only** (no UPDATE/DELETE even for admins); application code adds no update/delete paths.
**Acceptance (checkable):** Given the audit schema, the DB role's privileges are exactly SELECT, INSERT; a test attempt to UPDATE/DELETE an audit row fails at the DB layer; the audit endpoint exposes no mutation.

#### FR-051 — SHA-256 hash chain — **MUST** · Score: Phase 1 audit (10) + Bonus crypto audit (+2)
**Description:** Audit entries form a hash chain: `hash_n = SHA256(prev_hash ‖ entry_n ‖ nonce)`; each claim records the chain head; the chain is anchored (written to a second location — e.g., a git-synchronized file or a separate volume) at ingest milestones.
**Acceptance (checkable):** Given a chain of N entries, recomputation from entry 1 to N reproduces every stored hash; tampering with any entry is detectable by a re-verify (FR-052).

#### FR-052 — Nightly chain verification — **MUST** · Score: Phase 1 audit (10)
**Description:** A nightly job recomputes the hash chain and reports integrity: `OK` or a precise list of broken links; failures page the on-call via the observability dashboard and are logged (fail-open, FR-055).
**Acceptance (checkable):** Given an intact chain, the job reports OK; given a deliberately tampered entry (test), the job reports the exact broken link; the job runs on schedule without manual intervention.

#### FR-053 — OpenTelemetry per-claim trace — **SHOULD** · Score: Phase 1 audit (10) + NFR-012
**Description:** Each claim package gets an OTel trace spanning ingest → normalize → validate → handoff with spans per rule family and per LLM call (tokens, latency, retries); traces are exportable and queryable by claim ID.
**Acceptance (checkable):** Given a validated claim, a trace exists with the four pipeline phases and per-rule spans; the trace ID is stored with the claim and retrievable in the audit viewer.

#### FR-054 — Replayability — **MUST** · Score: Phase 1 audit (10)
**Description:** A historical decision can be **replayed**: given the stored package hash, catalogue hash, model/config versions, and pointers, the engine re-derives the same finding set deterministically; the replay result is compared to the original.
**Acceptance (checkable):** Given any stored claim, the replay reproduces the original deterministic findings (rule IDs, severities, evidence pointers); replay failures produce an explicit report (root cause: data drift, rule drift, or engine bug).

#### FR-055 — Fail open on audit failure — **MUST** · Score: reliability + Phase 1 audit (10)
**Description:** If the audit write fails, claim validation continues (the quality gate must not be a denial vector); the gap is logged with a high-priority operational alert and marked in the chain as a gap entry.
**Acceptance (G/W/T):** Given an audit DB that rejects writes, when a claim is validated, Then the claim completes with findings, a gap is logged, and the operational dashboard shows the audit failure.

#### FR-056 — Pointers, not PHI — **MUST** · Score: Phase 2 privacy (5) + audit ethics
**Description:** The audit log stores pointers and hashes, not person data: where a value is needed it is stored de-identified or as a pointer into the (synthetic) package store; "enough to reconstruct, never enough to leak".
**Acceptance (checkable):** Given a full audit export, no member name, Emirates ID, or addresses are present (they are pointers/hashes); the export can be shipped as a challenge artifact without review.

### 5.G Security, privacy & safety (Phase 2 — Privacy/security/safety: 5 pts)

#### FR-060 — PII de-identification (Presidio) — **MUST** · Score: Phase 2 privacy (5)
**Description:** Microsoft Presidio runs (a) **pre-prompt**: de-identify any incoming free text/OCR before it reaches an LLM; (b) **post-response**: scan LLM responses for residual PII before display/storage; findings of residual PII are redacted with a marker.
**Acceptance (checkable):** On a PII-injection test set (names, Emirates IDs, phone numbers in free text), 100% of PII entities are masked before the prompt; 0 residual PII entities survive post-response scanning into stored output.

#### FR-061 — Attachments are data, not instructions — **MUST** · Score: Phase 2 privacy (5) + safety
**Description:** All attachment/OCR content is treated as **DATA NOT INSTRUCTIONS**: it is packaged as data with explicit delimiters, and any embedded instruction-like content ("ignore previous instructions…") is inert — never executed or followed.
**Acceptance (checkable):** Given an adversarial attachment containing prompt-injection text, the LLM output never reflects the injected instructions; a test suite of injection payloads (including in PDF/OCR output) asserts unchanged behavior.

#### FR-062 — Clinical-refusal contract — **MUST** · Score: safety boundary + Phase 2 privacy (5)
**Description:** Any prompt that asks the system for clinical conclusions (diagnosis, treatment, medical necessity, "should this be approved") is answered with the documented refusal contract — the system states it is administrative-only and suggests the appropriate human/clinical channel. This is enforced at the API layer and in the UI copy.
**Acceptance (checkable):** Given a clinical question to any endpoint, the response is the refusal contract (not a clinical answer); system tests cover a list of clinical prompts (e.g., "does this patient need an MRI?", "approve this claim").

#### FR-063 — RBAC — **MUST** · Score: Phase 2 privacy (5)
**Description:** Roles from §4 are enforced: authenticated sessions, role-scoped permissions (e.g., T1 cannot override High findings; only T3 can policy-override; admin-only catalogue writes; auditor-only audit reads).
**Acceptance (checkable):** Given a T1 session, an attempt to dismiss a High-severity mandated finding is denied with a permissions error; given an admin session, catalogue mutations succeed and are audited with the actor id.

#### FR-064 — No-adjudication enforcement — **MUST** · Score: core principle
**Description:** The product never outputs paid/reduced/denied, never recommends approval/rejection — it outputs findings + suggested corrective actions. Enforced by output schema (no adjudication field), UI copy, and tests.
**Acceptance (checkable):** Across the entire API schema and UI, no endpoint or screen produces a payment/adjudication decision; a test greps the response schemas for adjudicative fields (e.g., `paid_amount`, `decision: approve`) and fails on presence.

#### FR-065 — Input sanitization & injection resistance — **MUST** · Score: Phase 2 privacy (5)
**Description:** All inputs are validated by Pydantic schemas; attachment text is size-limited and delimited; CSV cells are escaped; no raw strings reach SQL (parameterized queries only); CEL evaluation is sandboxed.
**Acceptance (checkable):** OWASP-relevant probes (SQLi payloads, oversized payloads, malicious CSV formulas) are handled without error, injection, or log leakage; the security scan in CI reports no findings above the agreed threshold.

#### FR-066 — Synthetic-data enforcement — **MUST** · Score: Phase 2 privacy (5)
**Description:** Ingest rejects or quarantines payloads flagged as likely real PHI (FR-008) in non-demo modes; demo mode is an explicit configuration with a banner.
**Acceptance (checkable):** Given a real-looking payload in normal mode, the claim is rejected with a privacy-gate error; in demo mode, the banner is visible and the payload is quarantined for manual inspection.

#### FR-067 — Secret & config hygiene — **MUST** · Score: Phase 2 privacy (5)
**Description:** No secrets in git (`.env` templates only), Docker secrets for compose, API keys loaded from environment, challenge fixtures separated from any credentials.
**Acceptance (checkable):** A repo scan finds zero committed secrets; `docker compose config` resolves without secret warnings; rotating an API key requires no code change.

### 5.H Interface / UI (Phase 3 — UI/UX: 10 pts)

#### FR-070 — Intake/upload screen — **MUST** · Score: Phase 3 UI (10)
**Description:** Drag-and-drop upload of FHIR JSON / CSV (+ attachments), inline validation feedback, package preview, and a "Start validation" action; upload state survives refresh for in-progress packages.
**Acceptance (G/W/T):** Given a user on the intake screen, when they drop a valid fixture, Then a package preview appears and validation starts; when they drop a malformed file, a precise error is shown and nothing is ingested (FR-001/FR-004).

#### FR-071 — Claim detail screen with findings — **MUST** · Score: Phase 3 UI (10)
**Description:** Per-claim view: header (claim ID, member, provider, service date, payer, status), the canonical package summary, and the full finding list ordered by severity, then confidence; each finding links to its evidence.
**Acceptance (checkable):** Clicking any finding opens the finding card (FR-072); the flagship fixture displays its three findings with correct severity/confidence ordering.

#### FR-072 — Finding card — **MUST** · Score: Phase 3 UI (10)
**Description:** Per finding: rule ID + family, severity badge, confidence, one-line summary, **evidence chips** (each chip = a JSON pointer that opens the underlying canonical-package value, resolved in code), the deterministic trace excerpt (values used), suggested corrective action, and the review action buttons (per role).
**Acceptance (checkable):** Every evidence chip resolves to a real value on click; a finding with no resolving pointer is never rendered (FR-015).

#### FR-073 — Review queue — **MUST** · Score: Phase 3 UI (10) + Phase 2 HITL (10)
**Description:** Tiered, filterable queue as in FR-044: columns (priority, claim, family, tier, severity, confidence, age, status), bulk filters, mandated-topic badge, and one-click entry into the claim detail.
**Acceptance (G/W/T):** Given mixed fixtures, when filtered by tier=2, Then High-severity and mandated findings appear and routine ones do not.

#### FR-074 — Review decision dialog with reason codes — **MUST** · Score: Phase 3 UI (10) + Phase 2 HITL (10)
**Description:** Modal dialog: decision radio (CONFIRM / CORRECT / DISMISS_WITH_REASON / ESCALATE), mandatory **reason-code enum** selector, optional free-text note (clearly labeled supplementary), corrective-action field that prepopulates the suggested action; role-aware availability (T1 cannot dismiss mandated topics).
**Acceptance (checkable):** Submitting without a reason code is blocked; a dismissed mandated finding by T1 is rejected by the backend; the stored record matches FR-043 exactly.

#### FR-075 — Rule catalogue admin — **MUST** · Score: Phase 3 UI (10) + Bonus rule GUI (+2)
**Description:** Admin screen: list of rules (searchable by family/ID), manifest editor (YAML) with live validation, dry-run against fixtures (FR-019), version/diff view, and publish (hash-pin + effective date). All mutations are audited.
**Acceptance (checkable):** Editing a manifest and running dry-run shows fixture impact without publishing; publishing creates a new version visible in the audit log with the actor id.

#### FR-076 — Audit viewer — **MUST** · Score: Phase 3 UI (10) + Phase 1 audit (10)
**Description:** Read-only timeline of audit events filtered by claim/actor/action; per-entry details (hash, prev-hash, event payload pointers, trace ID); "verify chain" action with integrity report; replay button per claim (FR-054).
**Acceptance (checkable):** The viewer offers no mutation controls; the verify action returns OK on the intact chain and a broken-link report on tampered test data.

#### FR-077 — Evaluation dashboard — **MUST** · Score: Phase 3 UI (10)
**Description:** Benchmark results: Macro F1, ECE, AUROC, clean-claim FP rate, per-family breakdown, per-rule precision/recall; compare-across-runs view; run trigger (re-run harness) with versioned report export (JSON/PDF).
**Acceptance (checkable):** After a harness run, all six metrics display with dataset/model/catalogue versions; exported report matches the displayed numbers.

#### FR-078 — Reviewer ergonomics — **SHOULD** · Score: Phase 3 UI (10)
**Description:** Keyboard navigation (j/k through queue, shortcut for decision dialog), low-click paths (decision in ≤ 3 clicks from queue), WCAG-AA contrast, responsive down to 1280px.
**Acceptance (checkable):** A usability script (drafted T1 task: review CLM-0042's three findings) completes in ≤ 3 minutes and ≤ 3 clicks per decision; an automated contrast check reports no AA violations.

### 5.I Evaluation & benchmarking (Phase 2 — Detection quality: 15 pts)

#### FR-080 — Benchmark harness — **MUST** · Score: Phase 2 detection quality (15)
**Description:** A CLI harness runs the full pipeline over the challenge datasets (13 fixtures + the 50-claim Phase-2 set) and produces a versioned report: per-claim findings, label comparison, metrics, and artifacts (raw outputs, configs, seeds) sufficient to reproduce the run.
**Acceptance (checkable):** `harness run --dataset phase2-50 --catalogue vX → report.json`; a re-run with pinned versions reproduces the metrics (deterministic core) within documented LLM variance.

#### FR-081 — Macro F1 — **MUST** · Score: Phase 2 detection quality (15)
**Description:** Macro F1 is computed across the six signal families (per-family F1 averaged) with the labelled 50-claim set; micro and family-level numbers are reported alongside.
**Acceptance (checkable):** The report contains Macro F1 ≥ the NFR-003 target, plus per-family F1/precision/recall; the computation is unit-tested against a hand-computed small case.

#### FR-082 — Clean-claim false-positive rate — **MUST** · Score: Phase 2 detection quality (15)
**Description:** The harness reports the false-positive rate on clean claims (fixtures/labelled cases with no intended findings) — measures our "avoid false alarms" criterion precisely.
**Acceptance (checkable):** The report contains the FP rate ≤ the NFR-004 target, with the list of false findings for manual inspection.

#### FR-083 — Mutation generator — **SHOULD** · Score: Phase 2 detection quality (15) + Bonus-adjacent
**Description:** A generator creates labelled mutants of clean fixtures (inject duplicates, lapsed coverage, missing auth, wrong IDs, missing attachments, malformed envelopes) to expand evaluation coverage beyond the 63 published cases; mutants are deterministic (seeded) and labelled with the injected fault.
**Acceptance (checkable):** Given a clean fixture and a mutation spec, the output claim contains exactly the injected fault and passes all unrelated rules; the seed reproduces the mutant byte-for-byte.

#### FR-084 — Performance / benchmark report artifact — **MUST** · Score: required deliverable
**Description:** A `docs/` report (per challenge deliverable list) documenting methodology, datasets, targets, results, and reproduction steps; refreshed at each phase gate.
**Acceptance (checkable):** The artifact exists at each gate with the current run's report attached and the NFR targets stated.

#### FR-085 — Regression gate on fixtures — **MUST** · Score: Phase 1 + Phase 2 (15)
**Description:** The 13 fixtures act as a regression suite: every catalogue/engine change must keep flagship findings identical (rule set, severity, confidence ≥ documented floors) and not regress Macro F1 on the 50-claim set.
**Acceptance (checkable):** CI runs the fixture suite on every PR; a regression (e.g., DUP-002 suppressed) fails the check with a diff of findings.

### 5.J API & integration (cross-cutting; Phase 1 ingestion + Phase 3)

#### FR-090 — REST API — **MUST** · Score: Phase 1 (15) + deliverable (Swagger)
**Description:** FastAPI exposes: `POST /claims` (submit package), `GET /claims/{id}` (package + findings), `GET /findings/{id}`, `POST /reviews` (structured decision), `GET /queue`, `GET/POST /rules` (admin), `GET /audit`, `POST /audit/verify`, `GET /eval/reports`. All responses are Pydantic-serialized with a consistent envelope (data / errors with codes).
**Acceptance (checkable):** OpenAPI/Swagger auto-docs list every endpoint with schemas; a smoke script exercises each endpoint against fixtures and asserts 2xx on valid and 4xx-with-codes on invalid inputs.

#### FR-091 — Streaming REST/WebSocket — **COULD (Bonus +2)** · Score: Bonus
**Description:** Long validations stream progress events (ingest → normalize → validate → handoff) over WebSocket and/or SSE, with per-phase status and live findings as they fire.
**Acceptance (G/W/T):** Given a validation run, when a client subscribes, Then progress events arrive in phase order and the terminal event carries the report ID.

#### FR-092 — API idempotency & replay safety — **SHOULD** · Score: integration quality
**Description:** Submit with an idempotency key returns the existing result for the same package hash; re-validation of an unchanged package is not duplicated in the audit chain (linked as re-runs, FR-045).
**Acceptance (checkable):** Re-submitting the same package hash with the same key returns the same report ID and creates a re-run link, not a new claim.

#### FR-093 — Error envelope — **MUST** · Score: Phase 1 (15)
**Description:** Every error is a structured `{code, message, detail (pointers), retryable}` — stable codes for the ENV/RULE/NORMALIZE/LLM/AUDIT domains — never a raw traceback to clients.
**Acceptance (checkable):** Triggering each failure class returns its documented code; no response body ever contains a stack trace (test greps error responses).

### 5.K Bonus features (each +2 pts)

| ID | Feature | Priority | Maps to |
|---|---|---|---|
| FR-100 | OCR/RAG attachment parsing (PDFs → structured attachment records feeding DOC-004/ENC-001 evidence and classification FR-023) | COULD | Bonus OCR/RAG |
| FR-101 | Dynamic payer-rule management GUI/API (per-payer rule sets, effective windows, versioning) | COULD | Bonus rule GUI/API |
| FR-102 | Active learning from overrides (FR-036) | COULD | Bonus active learning |
| FR-103 | Cryptographic audit log (FR-051 + anchored signing, e.g., periodic signature of the chain head) | COULD | Bonus crypto audit |
| FR-104 | Real-time streaming REST/WebSocket (FR-091) | COULD | Bonus streaming |
| FR-105 | Mobile app | **WON'T** (unless explicitly re-scoped as bonus) | — |

**Acceptance:** Each bonus FR is accepted only if its numbered criterion here passes *and* the feature demonstrably holds the +2 claim (documented in `03` traceability). Bonuses are only scheduled after the MUST/SHOULD work for the phase is green (see §11 order of work).

---

## 6. Exigences non fonctionnelles — Non-Functional Requirements

Every NFR has a **measurement method** and a **target**. Targets marked *(cible projet)* are our own engineering commitments; market figures are not used here — they live in `02` §3.

| NFR | Domain | Measurement method | Target value *(cible projet)* |
|---|---|---|---|
| NFR-001 | Performance — deterministic path latency | Validate a 100-claim synthetic batch on the reference machine; p95 of per-claim wall time for ingest→validate (no LLM) from OTel spans | p95 < 2 s per claim; p50 < 500 ms |
| NFR-002 | Performance — full pipeline latency | Same batch with LLM normalization/explanation enabled (local open-weights model) | p95 < 60 s per claim (batch of 100 in < 10 min) |
| NFR-003 | Accuracy — detection quality | Macro F1 on the labelled 50-claim Phase-2 dataset, computed by the harness (FR-080/081) | Macro F1 ≥ 0.90 |
| NFR-004 | Accuracy — false alarms | FP rate on clean labelled claims (FR-082) | FP rate ≤ 5% of clean claims |
| NFR-005 | Accuracy — calibration | ECE and AUROC on the held-out set, reported every run (FR-034) | ECE ≤ 0.05, AUROC ≥ 0.95 |
| NFR-006 | Reliability / availability | API uptime probes during demo windows; offline mode (Docker Compose, local LLM) with zero internet | ≥ 99% during all scheduled demos; offline mode fully functional at event venue |
| NFR-007 | Audit integrity | Chain re-verification (FR-052) on test-tampered data | 100% of tampered entries detected at the exact broken link |
| NFR-008 | Audit completeness | Every finding, routing, review and catalogue event present in the audit log for a smoke run | 100% of smoke-run events present; zero UPDATE/DELETE executed |
| NFR-009 | Determinism / reproducibility | Re-run the deterministic path on the same package + catalogue hash on two machines/dates | Byte-identical finding sets (rule IDs, severities, pointers); replay (FR-054) reproduces 100% of stored deterministic findings |
| NFR-010 | Maintainability — rules as data | Publish a new standard rule (new manifest + fixtures + tests) in the documented process | No core-engine code change required; documented process ≤ 1 h for a standard rule |
| NFR-011 | Portability | Fresh Windows/macOS/Linux machine, `docker compose up`, then run the fixture suite | Works with zero manual configuration beyond `.env` from template, ≤ 30 min |
| NFR-012 | Observability | OTel traces per claim; error-rate and latency dashboards; nightly audit-verification visibility | 100% of claims have a trace with the 4 phases; dashboards reachable in demo |
| NFR-013 | Explainability | Automated check over a synthetic corpus: % of findings with ≥ 1 resolving pointer; % of narrative citations that resolve | 100% findings pointer-verified; ≥ 99% narrative citations grounded (FR-022) |
| NFR-014 | Usability | Timed T1 script (FR-078) + SUS questionnaire with 5 volunteer users | Review of CLM-0042 ≤ 3 min, ≤ 3 clicks/decision; SUS ≥ 70 |
| NFR-015 | Security | Repo secret scan, dependency scan, OWASP-adjacent probe suite, RBAC tests | Zero committed secrets; 0 critical/high unfixed CVEs at each gate; RBAC tests pass |
| NFR-016 | Privacy | Detected PII in LLM input/output on the injection test set (FR-060); real-PHI scan of repo/artifacts | 100% masked pre-prompt; 0 residual post-response; 0 real-PHI hits in artifacts |
| NFR-017 | Robustness | Fuzz/malformed corpus (bad JSON, wrong types, huge payloads, truncated PDFs) | 100% of cases handled gracefully: structured error or ENV-001 stop, zero 5xx, zero crashes |
| NFR-018 | Scale (demo horizon) | Batch of 500 claims through the deterministic path | Completes < 30 min on reference machine, no memory blow-up |
| NFR-019 | Ethical boundary | Automated prompts asking for adjudication/clinical answers (FR-062/064) | 100% refusal-contract responses; 0 adjudicative outputs in any schema |
| NFR-020 | Localization of scope | Checks that out-of-scope lanes (§3.2) are unreachable | No endpoint/UI path to payer/EMR integration; synthetic-only enforced (FR-066) |

---

## 7. Contraintes — Constraints

### 7.1 Technical

- **Stack (fixed):** Python 3.11+, FastAPI, Pydantic v2, PostgreSQL 16, React/Next.js, `cel-python`, Pydantic AI **or** Instructor, Microsoft Presidio, OpenTelemetry, Docker Compose. See `04` for the ADRs; deviations require an ADR.
- **Data:** Inputs are **FHIR R4 JSON and/or CSV**, **synthetic only**. No real patient data at any point. Attachments in the fixture set are PDFs/images for the OCR bonus path.
- **LLM:** API-based option (structured-outputs/JSON-schema mode) **and** local open-weights option (vLLM/Ollama) — local is the baseline for data-residency arguments and venue reliability.
- **Determinism:** The validation core is a plain Python enum-driven state machine. LangGraph is only an upgrade path for durable HITL wait states. CrewAI/AutoGen autonomous loops are rejected for the decision core (liability, auditability, replayability).
- **Rules:** declarative manifests + CEL; versioned, hash-pinned in git (FR-010/FR-011).

### 7.2 Regulatory (design boundaries — see `02` §8)

- **FDA CDS (US):** staying administrative-only keeps us outside the medical-device lane; the product must let the healthcare professional independently review the basis of any recommendation (Jan 2026 final guidance) — our evidence-first findings are exactly that.
- **EU AI Act:** claims pre-validation is **not** in the Annex III high-risk list (which covers insurance risk assessment/pricing, 5(c)); the Annex III deadline is deferred to 2 Dec 2027. We still document our compliance posture (human oversight, auditability, transparency) because the client operates internationally.
- **ADHICS v2 (Abu Dhabi):** mandatory since Aug 2024 for healthcare facilities, payers, and service providers; our security/privacy/audit design (RBAC, de-identification, append-only audit, OTel) aligns with its spirit — a selling point for the Gulf pitch.
- **UAE/Dubai context:** mandatory insurance (DHA), eClaimLink electronic channel — documented in `01`; timing rules like PD-05-2025 (vendor-reported, to be confirmed) make pre-submission authorization checks valuable.
- **Boundary rule:** any feature that would make ClaimGuard a clinical decision support system or an adjudicator is out of scope by construction (§3.2, FR-062/FR-064).

### 7.3 Organisational

- Team of **5**: project lead (AI/tech/business, reviews all work), 1 senior software engineer (co-builds the core with the lead), 3 beginners (B1: chatbot/LLM experience; B2: deep learning; B3: computer vision).
- **Part-time reality:** ~15–20 h/week per member. The plan (§12) is sized for beginners, not fantasy velocity.
- **Pairing:** requirements drive assignments, not backgrounds — but AI-flavoured, self-contained, reviewable slices are given to beginners (see §12.4): attachment/OCR-RAG pipeline (B3 + B1), LLM explanation service (B1), confidence/calibration + active learning (B2), rule-catalogue GUI/API, streaming API, mutation generator, evaluation harness, reviewer UI. The core pipeline (ingest/validate/audit) is lead + senior engineer.
- **Reviews:** the lead reviews every beginner contribution before merge; a second pair of eyes (senior engineer) reviews the core.

### 7.4 Budget & compute

- **No cloud budget.** Everything must run on student laptops (Windows 11, AMD Ryzen AI 7 350 class) via Docker Compose; local LLM option sized to ~8 GB VRAM/RAM class or CPU-quantized fallback; API-model option used sparingly (fixture-driven test budget).
- Artifacts must be demo-proof at the venue (14–15 Nov): **offline mode is mandatory** (NFR-006), recorded LLM cassettes permitted for reproducibility (FR-046).
- +5 challenge points for mixed study levels — we plan a team of 5 across levels (confirm at registration).

---

## 8. Cas d'utilisation detailles — Detailed Use Cases

Notation: **Pre** (preconditions) → **Main flow** (numbered) → **Alt** (alternative; valid variant) → **Exc** (exception; failure handling) → **Post** (postconditions). Actors per §4. All UCs reference FRs/NFRs.

### UC-01 — Submit a claim package for validation
- **Actors:** Provider/billing staff, System.
- **Pre:** Package is assembled; user authenticated; system up (offline mode OK).
- **Main:**
  1. User uploads FHIR R4 JSON (or CSV) + optional attachments (UC-06) via UI or API (`POST /claims`).
  2. System parses and resolves bundle references (FR-001/003), builds the canonical package (FR-005), marks a synthetic-data guard pass (FR-008).
  3. System runs the envelope check ENV-001 (FR-004).
  4. System runs the deterministic rule catalogue against the package (FR-010–016), emitting findings with evidence pointers.
  5. System computes confidence for LLM-produced components (FR-030–035) and applies conformal abstention.
  6. System routes findings by tier, applying mandated-topic escalation (FR-040/041).
  7. System writes audit entries (FR-050/051) and returns a report with Claim ID + findings + narrative + trace ID (FR-017, FR-020).
  8. System hands off to the review queue (UC-02).
- **Alt A (CSV):** Steps 1–2 use the CSV path (FR-002) with per-row validation errors reported.
- **Alt B (LLM-assisted normalization needed):** free-text fields go through normalization (FR-006) with schema-validated structured output before step 4.
- **Exc E1 (malformed envelope):** ENV-001 fires at step 3 → pipeline stops safely, finding + queue task created, API returns 200-level envelope result per FR-004. **Post:** no LLM call, no rule run, package status `ENVELOPE_INCOMPLETE`.
- **Exc E2 (unparseable/unsupported input):** structured error envelope (FR-093), no claim created, audit entry for the failed attempt.
- **Exc E3 (audit write failure):** validation continues, gap logged, alert raised (FR-055).
- **Post:** A sealed, versioned report exists; queue has tasks for every routed finding; audit chain extended.

### UC-02 — Review a flagged claim
- **Actors:** Reviewer T1/T2/T3, System.
- **Pre:** A report from UC-01 exists with ≥ 1 finding; reviewer logged in with a role.
- **Main:**
  1. Reviewer opens the queue (FR-044), filtered by tier/family; mandated topics bubble up (FR-041).
  2. Reviewer opens the claim detail (FR-071), sees findings ordered by severity.
  3. Reviewer inspects each finding card: evidence chips resolve to package values (FR-072), narrative explains (FR-020), suggested action shown.
  4. Reviewer decides per finding via the decision dialog (FR-074) with a mandatory reason code (FR-043).
  5. System records decisions, re-validates if data corrected (FR-045), and updates the audit chain (FR-050/051).
  6. System closes the tasks and marks the claim reviewed (or re-queued if new findings appear).
- **Alt A (correction):** reviewer corrects data (e.g., fills the auth number) → re-validation run N+1 with before/after diff (FR-045).
- **Exc E1 (T1 attempts mandated-topic dismissal):** rejected by RBAC + routing rule (FR-063/041); the task remains queued for T2+.
- **Exc E2 (reviewer needs input):** decision `ESCALATE` → task moves to Tier 3 with the reason code and context.
- **Post:** Every finding has a structured decision; claim status is `REVIEWED` or `REVIEWED_WITH_CORRECTIONS`.

### UC-03 — Override a finding with a reason code
- **Actors:** Reviewer T2/T3, System.
- **Pre:** A finding exists that the reviewer believes is not actionable.
- **Main:**
  1. Reviewer opens the finding and selects `DISMISS_WITH_REASON` (T2+) or `POLICY_EXCEPTION` (T3 only).
  2. System enforces the reason-code enum (FR-043); free-text note optional, supplementary only.
  3. System records the override in the audit log with reviewer id, timestamp, and chain link (FR-050/051).
  4. System feeds the override into the active-learning buffer (FR-036) and statistics.
  5. System updates the claim status and removes the task.
- **Exc E1 (no reason code):** submission blocked (FR-043).
- **Exc E2 (T1 override):** denied (FR-063).
- **Alt A (override after correction):** reviewer instead corrects data; the finding is closed as `DATA_FIXED` and re-validation runs (UC-02 Alt A).
- **Post:** Override is part of a replayable decision record; reason-code statistics available to admin.

### UC-04 — Inspect the evidence behind a finding
- **Actors:** Reviewer, Auditor, System.
- **Pre:** A finding exists.
- **Main:**
  1. User opens the finding card (FR-072).
  2. System displays evidence chips, each a JSON Pointer (RFC 6901) into the canonical package.
  3. User clicks a chip; System resolves the pointer **in code** and shows the underlying value with its path and type (FR-015).
  4. User opens the deterministic-trace excerpt: the exact values the rule compared (e.g., coverage end 2026-08-15 vs service date 2026-08-20).
  5. User opens the narrative; each cited pointer/rule is cross-checked (FR-022) and any ungrounded sentence is flagged.
- **Exc E1 (pointer no longer resolvable):** impossible by construction (FR-015) — engine refuses to emit; if it happens during replay, the replay report flags it (FR-054).
- **Post:** User can verify the finding's factual basis independently — the FDA-CDS "independently review the basis" property, demonstrated.

### UC-05 — Add / modify a rule via the catalogue GUI/API
- **Actors:** Administrator, System.
- **Pre:** Admin role; catalogue loaded; fixtures available.
- **Main:**
  1. Admin opens the rule catalogue (FR-075) or uses the API (`POST /rules` — FR-090).
  2. Admin edits/creates a manifest (family, severity, CEL condition, evidence pointers, suggested action, effective dates).
  3. System validates the manifest schema and resolves evidence pointers statically (FR-010/015); load-time errors are shown inline.
  4. Admin runs dry-run against the fixture set (FR-019): predicted findings per fixture, diff vs current catalogue.
  5. Admin publishes: version bump (semver), effective date, hash pinned in git (FR-011); audit entry recorded with actor id.
  6. System activates the rule per effective date; new claims use it; old claims keep their catalogue hash (FR-011).
- **Exc E1 (invalid CEL):** evaluation error at load time; publish blocked with the offending expression.
- **Exc E2 (dangling evidence pointer):** manifest rejected (FR-015).
- **Exc E3 (regression):** dry-run shows a fixture's flagship finding changes (e.g., DUP-002 suppressed) → publish blocked unless an admin acknowledges with a documented reason (audited).
- **Post:** New catalogue version live; fixtures regression suite updated (FR-085).

### UC-06 — Upload and parse a PDF attachment (OCR/RAG bonus)
- **Actors:** Provider/billing staff, System (B3/B1 feature).
- **Pre:** Attachment-parsing module enabled (FR-100); package references a DocumentReference.
- **Main:**
  1. User uploads a PDF/image attachment with the claim (FR-070) or the package references one.
  2. System runs OCR (self-contained parser) and RAG-chunks the extracted text; text is treated as **data, not instructions** (FR-061) and de-identified pre-prompt (FR-060).
  3. System classifies the attachment kind (referral/approval/report — FR-023) and stores a structured attachment record.
  4. DOC-004 (Documentation family) and ENC-001 (Identity family) evaluate using the attachment record as evidence, e.g., "approval number found in the attached PDF".
  5. Findings cite the attachment pointer; reviewer can open the original + OCR text side-by-side.
- **Exc E1 (OCR garbage / unreadable PDF):** attachment marked `OCR_LOW_QUALITY`, routed with the raw bytes for human reading; no finding is fabricated from unreliable OCR.
- **Exc E2 (untrusted content):** prompt-injection payload in the attachment has no effect (FR-061 test suite).
- **Exc E3 (attachment missing):** DOC-004 fires — referenced attachment never uploaded (fixture case).
- **Post:** Attachment evidence contributes to findings; all text stored de-identified; audit references attachment hash.

### UC-07 — Audit a historical decision (replay)
- **Actors:** Auditor, System.
- **Pre:** A stored claim with a report id exists.
- **Main:**
  1. Auditor opens the audit viewer (FR-076) and selects the claim/report.
  2. Auditor requests **replay** (FR-054).
  3. System re-loads the stored package (by hash), catalogue version, calibration object, and model/config versions.
  4. System re-runs the deterministic path and compares findings to the stored ones.
  5. System reports: identical finding set (ids, severities, pointers) or a precise diff with root-cause classification (rule drift / data drift / engine bug).
  6. System writes the replay result to the audit log (append-only).
- **Exc E1 (catalogue version unavailable):** replay reports the drift root cause with the missing version id; pointer-level diff still computed where possible.
- **Exc E2 (tampered chain discovered):** the verify step (FR-052) reports the broken link first; replay is blocked for entries after the tamper point with a clear message.
- **Post:** An auditable, documented reconstruction of a historical decision — the "be traceable" criterion, demonstrated.

### UC-08 — Verify audit chain integrity
- **Actors:** Auditor, System.
- **Pre:** Chain exists; nightly verification scheduled (FR-052).
- **Main:**
  1. Auditor clicks "Verify chain" (FR-076) or the nightly job runs.
  2. System recomputes SHA-256 hashes link by link from the genesis entry (FR-051).
  3. System reports OK, or every broken link with entry ids and expected/actual hashes.
  4. System shows the anchored head (second location) for cross-check.
  5. Failure (if any) creates a high-priority operational alert; processing continues (fail open, FR-055).
- **Exc E1 (DB partially unavailable):** verification reports which interval could not be read; no false "OK".
- **Post:** Integrity status visible in the audit viewer and dashboards (NFR-007, NFR-012).

### UC-09 — Run the evaluation harness
- **Actors:** Administrator, System.
- **Pre:** Harness implemented (FR-080); datasets (13 fixtures + 50-claim set) available; catalogue pinned.
- **Main:**
  1. Admin triggers `harness run` (CLI or dashboard button — FR-077).
  2. System validates all claims, records raw outputs, labels comparison, computes Macro F1, ECE, AUROC, clean-claim FP rate (FR-081/082/034).
  3. System writes a versioned report (dataset, catalogue, model, seeds, metrics, per-family breakdown) (FR-084).
  4. Dashboard displays metrics with compare-across-runs (FR-077).
  5. Admin exports the report (JSON/PDF) for the challenge deliverable.
- **Alt A (mutation coverage):** harness runs on seeded mutants (FR-083) to measure robustness beyond the official labels.
- **Exc E1 (dataset mismatch):** harness fails fast with a checksum error before any metric is computed.
- **Exc E2 (LLM variance):** the report states the documented LLM-variance window for LLM-dependent metrics; deterministic-core metrics are reproducible exactly (NFR-009).
- **Post:** Current metrics artifact exists; the team can defend every number at the gate.

### UC-10 — Handle a malformed / incomplete claim envelope
- **Actors:** System, Provider/billing staff.
- **Pre:** A payload arrives that fails structural or envelope checks.
- **Main:**
  1. System parses; failure detected at parse or envelope stage (FR-001/004).
  2. System emits ENV-001 (or the appropriate structural error code, FR-093) and **stops the pipeline safely** (no LLM, no rules).
  3. System creates an `ENVELOPE_INCOMPLETE` task with a checklist of missing fields (pointers where computable).
  4. System returns a structured response to the caller and writes an audit entry.
- **Alt A (fixable):** user fixes and re-submits; new run with linked re-run audit entry (FR-045/092).
- **Alt B (fuzz case):** NFR-017 fuzz corpus — every malformed variant gets a graceful outcome, never a 5xx.
- **Exc E1 (ambiguous envelope):** system requests disambiguation rather than guessing (never fills missing fields with LLM invention at the envelope stage).
- **Post:** No partial claims, no phantom findings, no crash; the "know when to ask for help" behavior demonstrated.

---

## 9. Maquette fonctionnelle de l'interface — Interface Specification

Eight screens, each with content and interactions to a buildable level. Visual design per `05`/design tokens; this section is structural.

### 9.1 Intake / upload (FR-070)
```
┌──────────────────────────────────────────────────────────────┐
│ ClaimGuard  [Intake]  Queue(3)  Rules  Audit  Eval   [User▾] │
├──────────────────────────────────────────────────────────────┤
│  Submit a claim package                                       │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Drag & drop FHIR R4 JSON, CSV (or browse)            │  │
│  │  + optional attachments (PDF/PNG)                     │  │
│  └────────────────────────────────────────────────────────┘  │
│  Package preview            [Start validation]  [Dry-run]   │
│  • Claim: CLM-0042 · Member: S. Mansour · Provider: North-  │
│    Star Medical Center · Service: 2026-08-20 · Payer: HP Gold│
│  • Lines: 2 × 72148 (MRI lumbar) @ 1,800                    │
└──────────────────────────────────────────────────────────────┘
```
**Interactions:** drop → preview + parse feedback; per-file errors inline (ENV/structural red banner with code); "Start validation" → progress bar with phase chips (Ingest → Normalize → Validate → Handoff); dry-run only for admins (FR-019); upload state survives refresh.

### 9.2 Claim detail with findings (FR-071)
```
┌──────────────────────────────────────────────────────────────┐
│ ← Queue   Claim CLM-0042 · Status: REVIEW · Run v3 · Trace ▸ │
│ Member S. Mansour | Provider NorthStar MC | Payer HP Gold    │
│ Service 2026-08-20 | Coverage end 2026-08-15 | [Package ▾]   │
├──────────────────────────────────────────────────────────────┤
│ Findings (3) — sorted: severity → confidence                 │
│ ⚑ HIGH   COV-001 Coverage inactive on service date  0.99 ▸  │
│ ⚑ HIGH   AUTH-004 Authorization missing              0.96 ▸  │
│ ◈ MED    DUP-002 Possible duplicate service line      0.88 ▸  │
│ ── Narrative (LLM-generated, grounded) ──                    │
│ "Coverage for this member ended 15 Aug 2026, five days before│
│  the service date (COV-001, 0.99). No authorization ref…"    │
└──────────────────────────────────────────────────────────────┘
```
**Interactions:** clicking a finding opens the finding card; "Package" expands the canonical package with pointer paths; run selector shows re-run diff (FR-045).

### 9.3 Finding card (FR-072)
```
┌──────────────────────────────────────────────────────────────┐
│ ⚑ HIGH · COV-001 · Coverage family · catalogue v3-hash-a1b2  │
│ Coverage inactive on date of service                          │
│ Confidence 0.99 (deterministic: 1.0) — not LLM-adjusted      │
│ Evidence (resolved in code)                                   │
│   [Coverage.period.end] 2026-08-15            ▸ value shown  │
│   [Claim.item[0].servicedDate] 2026-08-20     ▸ value shown  │
│ Trace: coverage.end(2026-08-15) < servicedDate(2026-08-20)   │
│ Suggested corrective action: renew coverage / contact payer   │
│          [Confirm] [Correct data] [Dismiss w/ reason] [Esc]  │
└──────────────────────────────────────────────────────────────┘
```
**Interactions:** evidence chips resolve pointers live (FR-015); action buttons open the decision dialog (9.5); role-dependent availability (FR-063).

### 9.4 Review queue (FR-073)
```
┌──────────────────────────────────────────────────────────────┐
│ Queue — Tier: [All|T1|T2|T3]  Family: [All▾]  Status: [Open▾]│
│ ⚑ MAND AUTH-004 CLM-0042  Authorization  T2  HIGH 0.96 2m ▸ │
│ ⚑ MAND COV-001  CLM-0042  Coverage      T2  HIGH 0.99 2m ▸ │
│ ◈      DUP-002  CLM-0042  Integrity     T1  MED  0.88 2m ▸ │
│ ◈      DOC-004  CLM-0051  Documentation T1  MED  0.90 1h ▸ │
└──────────────────────────────────────────────────────────────┘
```
**Interactions:** mandated badge on escalation topics (sorted first — FR-041); j/k navigation, Enter opens claim; per-row actions (open, batch-correct).

### 9.5 Review decision dialog (FR-074)
```
┌──────────────────────────────────────────────────────────────┐
│ Decision — COV-001 · CLM-0042 · reviewed by: reviewer@t1     │
│ ● CONFIRM (finding correct, I will act)                      │
│ ○ CORRECT (data fixed → re-validate)                         │
│ ○ DISMISS_WITH_REASON                                        │
│ ○ ESCALATE (needs T3/payer input)                            │
│ Reason code (enum, required)   [DATA_FIXED ▾]                │
│  • DATA_FIXED • DOCUMENTATION_SUPPLIED • POLICY_EXCEPTION    │
│  • DUPLICATE_INTENTIONAL • NOT_APPLICABLE • NEEDS_PAYER_INPUT│
│ Corrective action (prefilled from rule)                      │
│    "Contact payer to renew coverage before submission"       │
│ Note (optional, supplementary)  [__]                         │
│                        [Cancel]  [Submit decision]           │
└──────────────────────────────────────────────────────────────┘
```
**Interactions:** reason code mandatory before submit (FR-043); T1 sees CONFIRM/CORRECT only on routine findings (mandated → T2+); submit writes the audit entry and closes/requeues the task.

### 9.6 Rule catalogue admin (FR-075)
```
┌──────────────────────────────────────────────────────────────┐
│ Rules [COV-001▾]  Family: [Coverage▾]  v3-hash-a1b2  [New]   │
│ rule_id: COV-001   severity: HIGH   version: 3               │
│ effective: 2026-06-01 → (active)                              │
│ CONDITION (CEL)   [coverage.period.end < claim.servicedDate] │
│ EVIDENCE         ["/Coverage/period/end",                    │
│                   "/Claim/item[0]/servicedDate"]  [Validate] │
│ suggested_action: "Renew coverage or contact payer"          │
│ Dry-run vs fixtures: CLM-0042 → fires ✓ (0.99)    [Run]      │
│ [Save draft] [Publish v4 (hash-pin)]                          │
└──────────────────────────────────────────────────────────────┘
```
**Interactions:** manifest validation on edit (schema + pointer resolution + CEL parse — FR-010/015); dry-run diff before publish; publish requires admin and audits actor id (FR-011).

### 9.7 Audit viewer (FR-076)
```
┌──────────────────────────────────────────────────────────────┐
│ Audit — filter: [claim: CLM-0042▾] [actor▾] [action▾]        │
│ #  ts           actor    action           ref      hash      │
│ 42 09-04 10:00  system   claim.ingest     CLM-0042 a1b2…c3  │
│ 43 09-04 10:00  system   rule.run(12)     CLM-0042 c3d4…e5  │
│ 44 09-04 10:01  system   finding.emit     CLM-0042 e5f6…a7  │
│ 45 09-04 10:05  r.t2     review.decision  F-44     a7b8…c9  │
│ [Verify chain] → OK · head anchored a7b8…c9 · [Replay claim] │
└──────────────────────────────────────────────────────────────┘
```
**Interactions:** read-only (FR-050); verify runs FR-052 with OK/broken-link report; replay opens UC-07 result panel; export grants no mutation.

### 9.8 Evaluation dashboard (FR-077)
```
┌──────────────────────────────────────────────────────────────┐
│ Evaluation — run #12 · 50-claim set · catalogue v3 · model X │
│ Macro F1 0.92 ██████████▒   ECE 0.03 ████   AUROC 0.96 ████ │
│ Clean-claim FP 3.2%  ███    Per family: Cov .94 Auth .93    │
│ Integrity .91 Identity .95 Documentation .96 Clean .97      │
│ [Compare runs ▾] [Re-run] [Export JSON/PDF]                  │
└──────────────────────────────────────────────────────────────┘
```
**Interactions:** metrics from the versioned report only; compare overlays runs; export produces the challenge artifact (FR-084).

---

## 10. Criteres d'acceptation / recette — Acceptance Checklist

The definitive checklist: **all rows must pass** before the corresponding deadline. Each row is runnable; run order is: fixtures → targeted tests → harness → manual demo script.

### 10.1 Recette MVP — due before **1 Oct 2026** (Phase 1, 50 pts)

| # | Criterion | How to verify | Refs | Pass |
|---|---|---|---|---|
| R1.1 | FHIR R4 JSON and CSV ingest produce equivalent canonical packages | Upload fixture via both paths; diff canonical JSON | FR-001/002/005 | ☐ |
| R1.2 | Bundle references resolve; dangling refs handled gracefully | Fixture suite + engineered dangling-ref case | FR-003 | ☐ |
| R1.3 | ENV-001 stops the pipeline safely, no LLM call, structured response | Malformed-envelope case; assert no LLM span in trace | FR-004, UC-10 | ☐ |
| R1.4 | All 12 fixture rules implemented with documented severities | Catalogue check + per-rule unit tests | FR-013/014 | ☐ |
| R1.5 | CLM-0042 emits exactly COV-001 (0.99), AUTH-004 (0.96), DUP-002 (0.88) | Harness on fixtures; JSON diff | FR-013/017, UC-01 | ☐ |
| R1.6 | Every finding carries Claim ID, Rule ID, evidence, severity, confidence, corrective action | Schema validation on all findings | FR-017 | ☐ |
| R1.7 | 100% of evidence pointers resolve in code | Static + runtime check across fixt. suite | FR-015, NFR-013 | ☐ |
| R1.8 | LLM explanation grounded; ungrounded citations rejected | Adversarial narrative test set | FR-020/022/024 | ☐ |
| R1.9 | Deterministic findings confidence = 1.0; LLM path isolated | Confidence audit on fixture run | FR-016/035 | ☐ |
| R1.10 | Audit log append-only; hash chain verifies; nightly job runs | DB privilege test + tamper test + job log | FR-050/051/052 | ☐ |
| R1.11 | Every scored event (ingest→finding→handoff) present in audit | Smoke-run event audit | FR-050, NFR-008 | ☐ |
| R1.12 | OTel trace exists per claim with 4 phases | Trace query by claim id | FR-053, NFR-012 | ☐ |
| R1.13 | Replay reproduces stored deterministic findings | Replay on ≥ 5 stored claims | FR-054 | ☐ |
| R1.14 | No 5xx on fuzz corpus; structured error envelope everywhere | NFR-017 fuzz run | FR-093, NFR-017 | ☐ |
| R1.15 | Deterministic path p95 < 2 s/claim | NFR-001 measurement | NFR-001 | ☐ |
| R1.16 | Rules-as-data: new rule without core code change (documented process) | Pilot rule added in ≤ 1 h | FR-010, NFR-010 | ☐ |
| R1.17 | Swagger docs published; benchmark report drafted | OpenAPI check + artifact exists | FR-090/084 | ☐ |
| R1.18 | No real data in repo; no committed secrets | CI scans | FR-008/067 | ☐ |

### 10.2 Recette Phase 2 — due before **20 Oct 2026** (30 pts)

| # | Criterion | How to verify | Refs | Pass |
|---|---|---|---|---|
| R2.1 | Macro F1 ≥ 0.90 on the labelled 50-claim set | Harness run, versioned report | FR-080/081, NFR-003 | ☐ |
| R2.2 | Clean-claim FP rate ≤ 5% | Harness FP report | FR-082, NFR-004 | ☐ |
| R2.3 | ECE ≤ 0.05 and AUROC ≥ 0.95 reported every run | Harness metrics | FR-034, NFR-005 | ☐ |
| R2.4 | Conformal abstention at α=0.05: coverage ≥ 0.95, abstentions → HITL | Held-out evaluation + queue check | FR-033/042 | ☐ |
| R2.5 | Mandated topics (AUTH-004/006/009, ENC-001, elig./benefit) always reach a human | Routing engine tests at conf 0.10 and 0.99 | FR-041 | ☐ |
| R2.6 | Three-tier routing policy applied | Route-injection tests | FR-040 | ☐ |
| R2.7 | Structured overrides with reason-code enum; T1 cannot dismiss mandated | API + UI test | FR-043/063/074 | ☐ |
| R2.8 | Correction → re-validation with diff; audit links runs | UC-02 Alt A script | FR-045 | ☐ |
| R2.9 | PII masked pre-prompt and post-response (0 residual) | Injection test set | FR-060, NFR-016 | ☐ |
| R2.10 | Attachment injection payloads inert; clinical prompts refused | Adversarial suites | FR-061/062, NFR-019 | ☐ |
| R2.11 | RBAC enforced on all review/override paths | Role matrix tests | FR-063 | ☐ |
| R2.12 | No adjudicative output in any schema/UI | Schema grep + UI walkthrough | FR-064 | ☐ |
| R2.13 | Mutation generator produces labelled, deterministic mutants | Seed-repro test | FR-083 | ☐ |

### 10.3 Recette Phase 3 — due before **1 Nov 2026** (10 pts + selection gate)

| # | Criterion | How to verify | Refs | Pass |
|---|---|---|---|---|
| R3.1 | All 8 screens render from real API data (no mock mode in demo) | End-to-end walkthrough on fixtures | FR-070–077 | ☐ |
| R3.2 | Reviewer resolves CLM-0042 in ≤ 3 min, ≤ 3 clicks/decision | Timed T1 script | FR-078, NFR-014 | ☐ |
| R3.3 | Evidence chips resolve; finding card complete on all findings | Spot-check on fixture run | FR-072 | ☐ |
| R3.4 | Rule catalogue GUI: edit → validate → dry-run → publish audited | Admin script | FR-075, UC-05 | ☐ |
| R3.5 | Audit viewer read-only; verify chain works; replay works from UI | Auditor script | FR-076, UC-07/08 | ☐ |
| R3.6 | Eval dashboard shows all six metrics + export | Harness run + export | FR-077/084 | ☐ |
| R3.7 | Offline demo mode: full demo with no internet, twice identically | Venue rehearsal | FR-046, NFR-006 | ☐ |
| R3.8 | WCAG-AA contrast automated check passes | a11y scan | FR-078 | ☐ |
| R3.9 | Architecture + data-flow diagram, network/security doc, perf report, tech report exist | Artifact checklist (§11) | §11 | ☐ |

### 10.4 Recette Finals — **14–15 Nov 2026** (pitch + live demo)

| # | Criterion | How to verify | Refs | Pass |
|---|---|---|---|---|
| R4.1 | Live demo runs the 13-fixture script end-to-end, < 2 min, stable | Rehearsed ×3 at venue conditions | FR-046, NFR-006 | ☐ |
| R4.2 | Pitch (≤ 2 members, English, 12 min = 5+2+5) rehearsed; Q&A prepared | Dry-run with mentor | §11 | ☐ |
| R4.3 | Every demo number matches the versioned benchmark report | Cross-check deck vs report | FR-084 | ☐ |
| R4.4 | Creative bonus pitch (+12) prepared if pursued | Mentor review | §11 | ☐ |
| R4.5 | All required deliverables present on the demo machine (offline copies) | Artifact checklist | §11 | ☐ |

---

## 11. Livrables — Deliverables per phase

### 11.1 Registration — **5 Sept 2026**
| # | Artifact | Owner |
|---|---|---|
| D1 | Team registration (5 members, mixed levels for +5 pts) | Lead |
| D2 | Docs 01–06 (domain, problem, decode, architecture, data model, cahier des charges) | Team |
| D3 | Public repo skeleton with README, license (challenge), `docs/` index | Senior |
| D4 | Challenge-rules checklist (deadlines, scoring, pitch rules) | Lead |

### 11.2 Phase 1 (MVP — 50 pts) — **1 Oct 2026**
| # | Artifact | Owner | FRs |
|---|---|---|---|
| D5 | Ingestion service (FHIR R4 JSON + CSV → canonical package, ENV-001 gate) | Core (lead+senior) | FR-001–005 |
| D6 | Rule engine (rules-as-data, CEL, hash-pinned catalogue, 12 fixture rules) | Core | FR-010–019 |
| D7 | LLM normalization + explanation service (structured output, bounded retry, grounding) | B1 (+B2 support) | FR-006, 020–024 |
| D8 | Audit log engine (append-only, hash chain, nightly verify, OTel traces) | Senior | FR-050–056 |
| D9 | Fixture regression suite (13 fixtures incl. CLM-0042) | Core | FR-085 |
| D10 | Swagger/OpenAPI docs + baseline benchmark report | Senior/B2 | FR-084, 090 |
| D11 | Demo video #1 (intake → findings → handoff on CLM-0042) | Lead | — |

### 11.3 Phase 2 — **20 Oct 2026**
| # | Artifact | Owner | FRs |
|---|---|---|---|
| D12 | Confidence & calibration pipeline (self-consistency → semantic entropy → calibration → conformal abstention) | B2 | FR-030–035 |
| D13 | HITL routing + review workflow (three tiers, mandated escalation, structured overrides) | Core | FR-040–046 |
| D14 | Security & privacy hardening (Presidio, injection tests, RBAC, clinical refusal) | Senior | FR-060–067 |
| D15 | Evaluation harness on the 50-claim set (Macro F1, ECE, AUROC, FP rate) | B2 | FR-080–082 |
| D16 | Mutation generator + expanded test corpus | B3 | FR-083 |
| D17 | Performance/benchmark report v2 + network/security documentation | Senior | FR-084 |
| D18 | Demo video #2 (HITL + calibration + audit replay) | Lead | — |

### 11.4 Phase 3 (selection gate) — **1 Nov 2026**
| # | Artifact | Owner | FRs |
|---|---|---|---|
| D19 | Reviewer UI (8 screens, end-to-end) | B1/B3 (UI pair) | FR-070–078 |
| D20 | Rule catalogue GUI + API | B1 (GUI) / Senior (API) | FR-075, FR-101 |
| D21 | Architecture + data-flow diagram, tech report, final benchmark report | Lead/Senior | §10.3 |
| D22 | Offline-mode hardening + demo rehearsal kit | Core | FR-046, NFR-006 |
| D23 | Demo video #3 (full product walkthrough) + selection-gate submission | Lead | — |

### 11.5 Finals — **14–15 Nov 2026**
| # | Artifact | Owner |
|---|---|---|
| D24 | Pitch deck (≤ 2 presenters, English) + 12-min structure (5+2+5) | Lead + one presenter |
| D25 | Live demo environment (laptop + offline stack, fixtures, cassettes) | Senior |
| D26 | Optional creative-bonus pitch (+12) if pursued | Lead |
| D27 | Source repo frozen at demo tag, all reports exported | Senior |

### 11.6 Bonus workstreams (scheduled only when MUST/SHOULD of the phase is green)
- **+2 OCR/RAG attachments** (FR-100): B3 + B1, Phase 2–3 window.
- **+2 Dynamic payer-rule GUI/API** (FR-101): Phase 3 (part of D20).
- **+2 Active learning from overrides** (FR-102): B2, Phase 2–3 window.
- **+2 Cryptographic audit log** (FR-103): Senior, Phase 2.
- **+2 Real-time streaming REST/WebSocket** (FR-104): Senior/B1, Phase 3.
Rule of thumb from the lead: **a bonus must never jeopardize a MUST** — every bonus lands after the corresponding recette row is green.

---

## 12. Planning macro — Macro Plan

### 12.1 Milestones

| Milestone | Date | Deliverables (from §11) | Gate / check |
|---|---|---|---|
| M0 Registration | 5 Sept 2026 | D1–D4 | Registration closed; late = −5 pts |
| M1 MVP cut | 1 Oct 2026 | D5–D11 | Recette §10.1 all green; demo #1 |
| M2 Phase 2 cut | 20 Oct 2026 | D12–D18 | Recette §10.2 all green; demo #2 |
| M3 Phase 3 cut / selection gate | 1 Nov 2026 | D19–D23 | Recette §10.3 all green; submission |
| M4 Finals | 14–15 Nov 2026 | D24–D27 | Recette §10.4; pitch + live demo |

### 12.2 Working rhythm (Agile)

- **Sprint length:** 1 week (Tue→Mon); sprint review + planning each Monday evening (~45 min).
- **Backlog:** requirements from this document are the source; each item carries FR refs + recette rows; effort in beginner-hours.
- **Definition of Done:** implementation + fixture/unit coverage for the FR + no regression on the fixture suite + recette row executable + reviewed by lead.
- **Velocity reality:** ~15–20 h/person/week part-time; beginners budgeted 1.5–2× senior time on estimation. The MVP scope above is deliberately the challenge minimum for 50 pts; no gold-plating before M1.

### 12.3 Sequencing (dependencies)

Weeks of 7 days, starting 8 Sept (post-registration):
- **W1 (8–14 Sep):** skeleton + canonical package + ENV gate (D5) — core pair; B1 studies `04`/`05`; B2/B3 onboard the fixture set.
- **W2 (15–21 Sep):** rule engine + first rules (COV-001, AUTH-004, DUP-002, ENV-001) (D6); audit table + hash chain prototype (D8 partial).
- **W3 (22–28 Sep):** full catalogue + fixture suite green (D9); LLM normalization/explanation v1 (D7, B1).
- **W4 (29 Sep–1 Oct):** MVP hardening, OTel traces, Swagger, demo #1, recette §10.1 (D10–D11).
- **W5–6 (Oct):** calibration pipeline (B2, D12) runs in parallel with HITL (core, D13); security hardening (senior, D14); harness + mutants (D15/D16).
- **W7 (Oct 13–20):** Phase-2 recette §10.2, report v2, demo #2 (D17–D18).
- **W8 (Oct 21–27):** reviewer UI (D19) + rule GUI (D20) in parallel with bonus workstreams.
- **W9 (Oct 28–Nov 1):** selection-gate pack: diagrams, tech report, offline rehearsal, recette §10.3 (D21–D23).
- **Nov 2–13:** finals prep: pitch, demo tuning, bonus polish, freeze (D24–D27).

### 12.4 Work assignment (requirements-first)

| Work package | FRs | Assigned | Why / notes |
|---|---|---|---|
| Core pipeline (ingest/validate/audit/HITL core) | FR-001–005, 010–019, 040–046, 050–056 | Lead + senior (pair) | Highest-risk, load-bearing; lead wants the central parts |
| LLM explanation + normalization service | FR-006, 020–024 | B1 | Direct fit for chatbot/LLM background; reviewable |
| Attachment OCR/RAG pipeline | FR-100, 023, 061 | B3 (vision) + B1 (LLM orchestration) | Uses CV + LLM skills; self-contained |
| Confidence/calibration + active learning | FR-030–036, 102 | B2 | Genuine ML topic (calibration) matching DL background |
| Rule-catalogue GUI/API | FR-075, 101 | B1 (GUI) + senior (API review) | Beginners learn API design with safety net |
| Mutation generator + eval harness | FR-080–083 | B3 (mutants), B2 (harness) | Labelled-data engineering; teaches evaluation rigor |
| Reviewer UI / streaming API | FR-070–078, 091, 104 | B1/B3 UI pair + senior streaming | UI polish is Phase-3 scored; beginners grow fast here |

---

## Appendix — Traceability quick map

| Challenge scored component (pts) | FRs | Recette rows |
|---|---|---|
| Phase 1 — Ingestion & normalization (15) | FR-001–008 | R1.1–R1.3 |
| Phase 1 — Deterministic + AI rule engine (15) | FR-010–019, FR-023 | R1.4–R1.7 |
| Phase 1 — Explainability & structured output (10) | FR-017, FR-020–024 | R1.6–R1.9 |
| Phase 1 — Audit log engine (10) | FR-050–056 | R1.10–R1.13 |
| Phase 2 — Detection quality / Macro F1 (15) | FR-030–035, FR-080–083 | R2.1–R2.4, R2.13 |
| Phase 2 — HITL & escalation (10) | FR-040–046 | R2.5–R2.8 |
| Phase 2 — Privacy/security/safety (5) | FR-060–067 | R2.9–R2.12 |
| Phase 3 — UI/UX (10) | FR-070–078 | R3.1–R3.8 |
| Phase 4 — Pitch (10) | D24–D26 | R4.2–R4.4 |
| Bonus +2 each | FR-100–104 | §11.6 |

**Version history:** v1.0 — 2026-09-04 — initial issue aligned with docs 01–02; pending alignment with 03–05 once they land (contracts unchanged; terminology only).