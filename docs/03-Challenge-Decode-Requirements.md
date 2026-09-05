# 03 — Challenge Decode & Requirements Traceability

> **Document:** The decoded CSTAM-VELODOC challenge — what is actually being asked, in Velodoc's own words, plus the point-by-point scoring breakdown and the **traceability matrix** that ties every scored requirement to a component, a spec reference, and an evidence artifact. This is the team's acceptance checklist.
> **Project:** ClaimGuard AI — CSTAM-VELODOC Challenge ("Trustworthy Agentic Copilot for Healthcare Claim Pre-Validation")
> **Audience:** Team, mentors (Dr. Wael Hilali, Bilel Said), jury.
> **Status:** v1.0 · 2026-09-04 · Aligned with docs 01, 02, 04–08.
> **Companion docs:** `04-Architecture.md` (8 ADRs, deterministic core + LLM at edges), `05-System-Design-Data-Model.md` (canonical model, DDL, rule YAML, 13 REST endpoints, benchmark generator), `06-Cahier-Des-Charges.md` (FR-001…FR-105, NFR-001…NFR-020, UC-01…UC-10, recette R1.x–R4.x), `07-Spec-Plan-Tasks.md` (EPICs FND…DEL), `08-Team-Roles-Sprints-Backlog.md` (T01–T44, S0–S10).
> **Conventions:** RFC 2119 keywords are normative. Every external claim carries its source URL. Velodoc's vocabulary is used exactly: **signals**, **findings**, **synthetic fixtures**, **claim package**, **review, don't adjudicate**, **quality gate**, **copilot**, **payer**, **reviewer**, **handoff**. Nothing here invents a statistic; where a number is an engineering target *we* set, it is marked "(cible projet)".

---

## 1. The mission in Velodoc's own words

Velodoc publishes the challenge material directly at **veloclaim.app** (mission slides) and **veloclaim.app/reference** (rule catalogue). The team should treat this doc as the ground truth: *the challenge is not "build a claims engine", it is "build a quality gate that behaves like a useful copilot".*

### 1.1 The six mission verbs (slide 09)

Slide 09's lede, verbatim: *"Six plain-language verbs. No architecture prescription. Just the behavior a useful quality gate should make visible."* The footer of the site: **"Built for review, not replacement."**

| Verb | Velodoc's definition (paraphrase) | ClaimGuard system capability | Where (doc reference) |
|---|---|---|---|
| **READ** | Understand the synthetic claim package | Ingest + Normalize: parse FHIR R4 JSON / CSV, resolve references, assemble the sealed canonical claim package (claim + patient + encounter + service) | FR-001…FR-005 (06 §5.A) |
| **CHECK** | Look for administrative problems and inconsistencies | Deterministic rule engine over the versioned R01–R15-based catalogue; produces **signals**, never judgments | FR-010…FR-018 (06 §5.B) |
| **EXPLAIN** | Show why something was flagged and what evidence supports it | Every finding carries title / detail / tone / source (JSON Pointer) / rule / confidence / next action; LLM narrative written **after** rules fire, grounded in resolving pointers | FR-015, FR-017, FR-020…FR-022 (06 §5.C) |
| **RECOMMEND** | Suggest what should be reviewed or corrected | `next_action` / `suggested_corrective_action` field on every finding — a suggestion to a human, never an adjudication | FR-017, FR-043 (06 §5.B/§5.E) |
| **ESCALATE** | Ask a human when the situation is uncertain or important | HITL router (three tiers, enum state machine): conformal abstention (α = 0.05) and **mandatory-topic escalation that is never confidence-gated** | FR-040…FR-042 (06 §5.E) |
| **RECORD** | Keep a trace of what was checked and recommended | Append-only audit log, SHA-256 hash chain, nightly verification, OTel traces per claim; replayability of any decision | FR-050…FR-056 (06 §5.F) |

Slide 10 — **Rules + AI + Humans = trustworthy copilot**, verbatim: *"Rules — For certainty. Repeatable checks for coverage, dates, required fields, duplicates, and amounts."* *"AI — For interpretation. Help connect evidence, summarize a finding, and surface ambiguity."* *"Humans — For oversight and accountability. Review uncertain or important decisions before they move on."* Footnote: *"Teams are free to choose their preferred technical approach."*

**How we exploit that freedom — deliberately.** The two loaded phrases are "No architecture prescription" and "Teams are free to choose their preferred technical approach". We use that freedom to make one strategic choice that shapes everything else:

1. **We do NOT build an autonomous agent loop.** CrewAI/AutoGen-style autonomous multi-agent systems are explicitly REJECTED for the decision core (ADR-001 family, `04` §2 P1). The decision path is a **plain Python, enum-driven, deterministic state machine** with rules evaluated in CEL — replayable, testable, and auditable by construction. An LLM is used only at the edges: normalization/OCR of free text, explanation narratives *after* rules fire, attachment classification, reviewer summarization (see `04` §6 for the full allowed/forbidden table).
2. **LangGraph is only an upgrade path**, not the v1 engine — the upgrade path is documented (ADR, `04`) but the MVP ships the deterministic core.
3. We choose **rules as data** (versioned YAML + CEL), **evidence-first findings** (every finding cites a resolving RFC 6901 JSON Pointer), **calibrated confidence with conformal abstention**, and an **offline-capable deployment** (Docker Compose, local/open-weights LLM profile) so the 14–15 Nov demo can never fail on internet access. (NFR-006, `06` §7.4.)

The freedom also has a boundary: slide 09's "no architecture prescription" means the *architecture* is free, not the *behavior*. The six verbs, the eight deliverables (§1.2) and the six evaluation criteria (§1.3) are the contract.

### 1.2 The eight deliverables (slide 11)

Slide 11, callout verbatim: *"The challenge gives you a meaningful problem, safe synthetic inputs, and room to choose the experience, reasoning, and workflow that make your answer convincing."*

| # | Deliverable (slide 11) | ClaimGuard component | Status |
|---|---|---|---|
| 1 | Receive synthetic healthcare claim data | Ingest gateway (FHIR R4 JSON + CSV), ENV-001 envelope gate (FR-001–004) | Component |
| 2 | Identify administrative claim risks | Deterministic rule engine, 6 signal families (FR-010–018) | Component |
| 3 | Connect findings to a rule or evidence | Finding contract: Rule ID + resolving JSON-Pointer evidence (FR-015, FR-017) | Component |
| 4 | Explain findings clearly | Grounded LLM narrative after rules fire (FR-020–022) | Component |
| 5 | Recommend what to review or correct | `suggested_corrective_action` on every finding (FR-017) | Component |
| 6 | Escalate uncertain or high-risk situations | HITL router: abstention + mandatory topics (FR-040–042) | Component |
| 7 | Keep an auditable history | Append-only hash-chained audit log (FR-050–056) | Component |
| 8 | Present findings in a usable interface | Reviewer UI: queue, finding cards with evidence chips, approval/override (FR-070–078) | Component |

### 1.3 The six evaluation criteria (slides 12 + 13)

| # | Criterion | Plain reading | Where we deliver |
|---|---|---|---|
| 1 | **Find real problems** | "Do not miss important issues" | Recall-oriented rule coverage: fixture rules + additions (§2), Macro F1 per family (FR-081) |
| 2 | **Avoid false alarms** | "Do not flag everything" | Deterministic rules (confidence 1.0 where it matters), clean-claim FP rate ≤ 5% (cible projet, FR-082) |
| 3 | **Explain itself** | "Show why a finding exists" | Evidence-first findings + grounded narrative (FR-015/020/022) |
| 4 | **Know when to ask for help** | "Use human review appropriately" | Conformal abstention + mandatory-topic HITL, never confidence-gated (FR-033/040/041) |
| 5 | **Be traceable** | "Record what happened" | Append-only hash chain, replay, OTel (FR-050–055) |
| 6 | **Be usable** | "Help someone understand and act" | Phase-3 reviewer UI + timed usability script (FR-070–078, R3.2) |

Slide 13, official scoring note verbatim: *"Macro F1 balances precision and recall across finding types. In plain language: catch the problems that matter without turning every claim into an alarm."* And: *"The detailed score can sit beside explainability, escalation, traceability, and usability. A high detection score is not enough if a person cannot understand what to do next."*

**Reading:** the F1 number is necessary but not sufficient — the other five criteria are scored qualitatively and demonstrably. Our benchmark report therefore always ships Macro F1 **alongside** ECE, AUROC, per-family precision/recall, and the clean-claim FP rate (FR-034/FR-077), and every demo script enacts criteria 3–6 end-to-end (FR-046).

---

## 2. The rules question, resolved

**Is the fictional rule catalogue published? YES.** Velodoc publishes a 15-rule fictional catalogue on **veloclaim.app/reference** (R01–R15). We build on it verbatim. The 13 challenge fixtures, however, use a set of 12 internal rule IDs (COV-001 … ENV-001) that do **not** map 1:1 onto R01–R15. This section reproduces both, reconciles them, and fixes the **merged authoritative rule table** our engine actually implements.

### 2.1 The published catalogue — R01–R15, verbatim (veloclaim.app/reference)

> R01 — Coverage active at the date of service?
> R02 — Required patient identifier present?
> R03 — Provider valid for the selected plan?
> R04 — Procedure supported by the plan?
> R05 — Required authorization present?
> R06 — Duplicate service line?
> R07 — Required information present?
> R08 — Dates and references consistent?
> R09 — Amount greater than zero?
> R10 — Required attachment present?
> R11 — Encounter reference resolves?
> R12 — Member and beneficiary match?
> R13 — Service location supported?
> R14 — Payer and plan are present?
> R15 — Claim status is reviewable?

### 2.2 The 13 fixtures and their rule IDs (as shipped by Velodoc)

| Fixture | Member / narrative | Family (fixture) | Fired rule (rule ID, confidence, evidence, next action) | Provider / date / payer | Notes |
|---|---|---|---|---|---|
| CLM-0042 | Sara / three problems | Coverage, Authorization, Integrity | COV-001 (High 0.99, `coverage.endDate`, "Verify eligibility and route to an administrative reviewer"); AUTH-004 (High 0.96, `authorization.reference`, "Locate the approval or request reviewer follow-up"); DUP-002 (Medium 0.88, `lines[0..1]`, "Compare source documents before changing either line") | NorthStar Medical Center / 20 Aug 2026 / HealthPlus Gold (coverage ended 15 Aug 2026) | Flagship; MRI 1,800 × 2 |
| CLM-0175 | Clean consultation | Clean | **No findings** — reviewNote: "No administrative signals were raised. A clean result is not an approval; it is a clear handoff for the normal workflow." | Harbor Family Practice / 10 Aug 2026 / Nourish Select (active) | The FP-rate anchor |
| CLM-0103 | Coverage ended mid-month | Coverage | COV-001 (High 0.98, `coverage.endDate`) | Cedar Ridge Clinic / 28 Aug 2026 / Afaq Standard (ended 22 Aug) | |
| CLM-0107 | Prior authorization expired | Authorization | AUTH-006 (High 0.94, `authorization.validTo`) | Riyadh Specialty Group / 18 Aug 2026 / HealthPlus Gold (expired 12 Aug) | |
| CLM-0110 | Referral mismatch | Authorization | AUTH-009 (Medium 0.86, `referral.specialty`) — reviewNote: "'Mismatch' is an explainable signal, not a clinical judgment." | Atlas Referral Network / 21 Aug 2026 / Nourish Select (GP referral vs specialist visit 375) | |
| CLM-0122 | Duplicate outpatient line | Integrity | DUP-002 (High 0.97, `lines[0], lines[1]`) | NorthStar Medical Center / 25 Aug 2026 / Afaq Standard (lab panel 90 × 2) | |
| CLM-0153 | Overlapping service dates | Integrity | INT-003 (Medium 0.84, `lines[0].period, lines[1].period`) — reviewNote: "The rule catches a structural collision; it does not infer what care happened." | Cedar Ridge Clinic / 12–15 Aug 2026 / HealthPlus Gold | |
| CLM-0114 | Member ID mismatch | Identity | ID-002 (High 0.99, `claim.memberId ↔ encounter.memberId`) | Harbor Family Practice / 07 Aug 2026 / Nourish Select | |
| CLM-0139 | Missing supporting attachment | Documentation | DOC-004 (High 0.95, `attachments[0].id`) | Riyadh Specialty Group / 16 Aug 2026 / Afaq Standard | |
| CLM-0146 | Provider identifier absent | Identity | ID-005 (High 0.99, `provider.identifier`) | Identifier not supplied / 14 Aug 2026 / HealthPlus Gold | |
| CLM-0161 | Malformed claim envelope | Documentation | ENV-001 (High 1.00, `claim.id, claim.serviceDate`) — reviewNote: "Normalization stops safely when the envelope is not complete enough to inspect." | — | Pipeline stop, fail-closed |
| CLM-0168 | Unknown encounter | Identity | ENC-001 (High 0.98, `encounter.reference`) — reviewNote: "A missing link is not treated as proof that the service did not happen." | Cedar Ridge Clinic / 11 Aug 2026 / Afaq Standard | Mandated escalation (FR-041) |
| CLM-0182 | Benefit limit reached | Coverage | COV-008 (Medium 0.89, `benefits.remainingUnits`) | Atlas Referral Network / 29 Aug 2026 / HealthPlus Gold (therapy unit 160 × 8) | No R-number covers this |

> **v2 note (2026-09-05) — fixture family labeling decision:** for the **12 fixture-backed rules, the fixture label is authoritative — always**. Velodoc publishes 13 synthetic fixtures, each labelled with a signal family; those are the only externally-published, externally-graded labels we possess. Our internal taxonomy is ours to invent; theirs is what a grader may compare our findings against — where the two conflict, **theirs wins**. This corrects two rules from our earlier internal choice: **ENV-001 = Documentation** (from **Integrity** — fixture CLM-0161 "Malformed claim envelope") and **ENC-001 = Identity** (from **Integrity** — fixture CLM-0168 "Unknown encounter"). Authority hierarchy: **fixture label > YAML manifest** for fixture-backed rules; the YAML manifest is the single source of truth **only** for rules with no fixture (our ADDED rules PYR-001, AMT-001, ST-001, CLEAN-001, ID-001, LOC-001 and catalogue rules R03, R04 — unchanged). Rationale: family drives severity assignment, HITL mandatory-escalation routing, UI colour-coding, and metrics grouping, and we do **not** yet know whether the graded Macro F1 is computed **per rule family or per individual rule** (§8 mentor question 2). Until that is answered, matching the published fixture labels is the strictly safer choice: it costs us nothing if scoring is per-rule, and protects us if it is per-family. What matters for scoring: six families (Coverage, Authorization, Integrity, Identity, Documentation, Clean), every fixture rule fires with the published rule ID, and all finding fields match the output contract.

### 2.3 Reconciliation — gaps in both directions

**Fixture rules with no published R-number (4 of 12):**
- **COV-008** (benefit balance exhausted) — R01–R15 has no benefit-balance rule. R04 (procedure supported by plan) is the closest *intent* (plan benefit supports the service), but it is about eligibility of the procedure, not remaining units. **Resolution:** keep COV-008 as our own extension inside the Coverage family, mapped "≈ R04 (benefit side)".
- **AUTH-009** (referral mismatch) — no R-number. The catalogue checks authorization presence/validity, not referral-to-service consistency. **Resolution:** keep as our own Authorization-family rule (our engine: "connect signal, don't infer care" — fixture reviewNote).
- **AUTH-006** (approval valid on service date) — R05 asks only "required authorization present?" **Resolution:** AUTH-006 is a *refinement* of R05 (validity window, overlaps R08's dates-consistency intent). Marked "R05 (extended)".
- **ID-002** (claim ↔ encounter identity match) — R12 asks "member and beneficiary match?" **Resolution:** ID-002 is an *extension* of R12's consistency intent to the claim↔encounter pair. Marked "R12 (extended)".

**Published R-numbers with no fixture (7 of 15):** R02, R03, R04, R09, R13, R14, R15. These are not exercised by any of the 13 fixtures. Because the Phase-2 50-claim validation dataset is not yet published to us (see §8, Q1), we cannot know whether it exercises them. **Strategy:** ship the cheap deterministic ones (R14, R09, R15; R02 optional) as ADDED rules — they cost hours, cannot false-positive on clean fixtures, and de-risk the benchmark; defer the data-hungry ones (R03, R04, R13) until we know the benchmark shape.

### 2.4 The MERGED AUTHORITATIVE RULE TABLE (what our engine implements)

Catalogue v1 (Phase-1 core): **15 detection rules + 1 informational signal = 16 entries.** Legend: `REQUIRED` = fixture-backed (the fixture is the regression test); `ADDED` = our choice, no fixture; `DEFERRED` = documented, not shipped in v1.

| Our rule ID | Family | Human name | What it checks | Default severity | Evidence source path | Maps to Velodoc R# | Maps to fixture | Notes |
|---|---|---|---|---|---|---|---|---|
| COV-001 | Coverage | Coverage active on date of service | `coverage.period` covers `claim.item.servicedDate`; fires when coverage ended before service | High (red) | `/coverage/period/end`, `/claim/item[i]/servicedDate` | R01 | CLM-0042, CLM-0103 | **REQUIRED.** Flagship; 0.99. Deterministic, confidence 1.0 |
| COV-008 | Coverage | Benefit balance available | `benefits.remainingUnits` ≥ billed units; fires when balance looks exhausted | Medium (amber) | `/benefit/remainingUnits`, `/claim/item[i]/quantity` | ≈ R04 (benefit side — no exact R#) | CLM-0182 | **REQUIRED.** Our extension; catalogue has no balance rule |
| AUTH-004 | Authorization | Required approval present | Where plan/policy requires prior approval, an `authorization.reference` resolves; fires when missing | High (red) | `/claim/item[i]/authorization/reference` | R05 | CLM-0042 | **REQUIRED.** 0.96; mandated escalation (FR-041) |
| AUTH-006 | Authorization | Approval valid on service date | `authorization.validFrom ≤ servicedDate ≤ authorization.validTo`; fires when expired/not-yet-valid | High (red) | `/authorization/validTo` | R05 (extended) | CLM-0107 | **REQUIRED.** Refines R05 presence → validity window |
| AUTH-009 | Authorization | Referral matches service | `referral.specialty` consistent with billed service specialty; mismatch is a signal, not a clinical judgment | Medium (amber) | `/referral/specialty`, `/claim/item[i].product` | — (no R#) | CLM-0110 | **REQUIRED.** Our extension; explainable-signal framing |
| DUP-002 | Integrity | Duplicate service line | Two lines with identical code/quantity/dates/amount within a claim | Medium (amber) | `/claim/item[0]`, `/claim/item[1]` | R06 | CLM-0042, CLM-0122 | **REQUIRED.** 0.88 / 0.97 |
| INT-003 | Integrity | Service periods do not overlap | Line service periods are pairwise disjoint; fires on structural collision only | Medium (amber) | `/claim/item[0]/period`, `/claim/item[1]/period` | R08 (dates/consistency) | CLM-0153 | **REQUIRED.** Never infers what care happened |
| ID-002 | Identity | Claim and encounter identity match | `claim.memberId == encounter.memberId`; fires on mismatch | High (red) | `/claim/memberId`, `/encounter/memberId` | R12 (extended) | CLM-0114 | **REQUIRED.** Extends R12 member↔beneficiary to claim↔encounter |
| ID-005 | Identity | Provider identifier present | `provider.identifier` non-empty; fires when absent | High (red) | `/provider/identifier` | R03 (precondition) | CLM-0146 | **REQUIRED.** R03 assumes a known provider; we check presence first |
| DOC-004 | Documentation | Referenced attachment present | Every referenced `DocumentReference.id` resolves to an uploaded/available attachment | High (red) | `/attachments[0]/id` | R10 | CLM-0139 | **REQUIRED.** 0.95 |
| ENC-001 | Identity | Encounter reference resolves | `encounter.reference` resolves inside the package; missing link ≠ proof service didn't happen | High (red) | `/encounter/reference` | R11 | CLM-0168 | **REQUIRED.** Mandated escalation (FR-041) |
| ENV-001 | Documentation | Minimum claim envelope | `claim.id`, `claim.serviceDate`, member, provider, ≥ 1 line present; on failure the pipeline **stops safely** (fail-closed: no LLM, no rules) | High (red, pipeline stop) | `/claim/id`, `/claim/servicedDate` | R07 (required-info variant) | CLM-0161 | **REQUIRED.** 1.00; the graceful-malformed-FHIR answer (Phase-2 guardrail) |
| PYR-001 | Coverage | Payer and plan are present | `insurance.coverage` payer id + plan reference both present and non-empty | High (red) | `/insurance/coverage` | R14 | — | **ADDED · priority 1.** Trivial, zero FP risk, likely in the 50-claim benchmark |
| AMT-001 | Integrity | Amount greater than zero | Every `item.net`/`item.unitPrice` > 0; fires on zero/negative | Medium (amber) | `/claim/item[i]/net` | R09 | — | **ADDED · priority 1.** Trivial, deterministic, benchmark-de-risking |
| ST-001 | Integrity | Claim status is reviewable | `claim.status` ∈ allowed reviewable set (e.g., active/cancelled handling defined); fires on non-reviewable status | Medium (amber) | `/claim/status` | R15 | — | **ADDED · priority 2.** Required for "review, don't adjudicate" semantics |
| CLEAN-001 | Clean | No administrative signals raised | Informational: fires on every package with zero findings — carries the CLM-0175 reviewNote contract verbatim ("clean result is not an approval; it is a clear handoff") | Info (neutral — **not** an alarm, no FP cost) | (no evidence node; cites full package hash) | — (maps to CLM-0175 semantics, no R#) | CLM-0175 | **ADDED · informational.** Makes the Clean family a real family and anchors the low-FP story |
| ID-001 | Identity | Required patient identifier present | `patient.identifier` non-empty; fires when the member's patient id is absent | High (red) | `/patient/identifier` | R02 | — | **ADDED · optional (v2).** Cheap; add if benchmark hints |
| LOC-001 | Integrity | Service location supported | Service location code is in the supported-location set (needs a location reference table) | Medium (amber) | `/claim/item[i]/location` | R13 | — | **DEFERRED.** Needs reference data not in fixtures; add only if benchmark exercises it |
| (R03 impl.) | Coverage | Provider valid for the selected plan | Provider is in the plan's network (needs plan-network table) | High (red) | `/provider`, `/coverage/plan` | R03 | — | **DEFERRED.** Needs network table; cheap later |
| (R04 impl.) | Coverage | Procedure supported by the plan | Billed procedure is covered by the plan's benefit catalogue (needs plan-benefit table) | High (red) | `/claim/item[i]/product`, `/coverage/benefit` | R04 | — | **DEFERRED.** Needs benefit table; revisit for Phase 2 |

**Coverage check:** all six families have ≥ 1 detection rule in the Phase-1 core (Coverage 2, Authorization 3, Integrity 3, Identity 3, Documentation 2, Clean 1 informational + the no-findings path). All 12 fixture rules are `REQUIRED` and regression-tested on the fixtures (FR-085, recette R1.4–R1.5). All 7 "orphan" R-numbers are either mapped to a fixture rule by extension (R03, R05, R07, R08, R12), added by us (R02 optional, R09, R14, R15), or explicitly deferred with a reason (R04, R13). The R-number↔rule mapping is documented per rule in `05` and machine-checked by the catalogue manifest (FR-010/FR-013).

---

## 3. Full scoring breakdown

Source: CSTAM Book pp. 17–19 (2026), as summarized in the challenge brief and mirrored in `06` §Appendix.

### 3.1 Base score — 100 points

| Phase | Item | Points | What is actually graded |
|---|---|---|---|
| **Phase 1 (MVP)** — due 1 Oct 2026 | Data ingestion & normalization | **15** | FHIR R4 JSON + CSV intake, canonical normalization, envelope handling |
| | Deterministic + AI rule engine | **15** | Rules catch the fixture problems; deterministic core + bounded AI use |
| | Explainability & structured output | **10** | Findings MUST contain: **Claim ID, Rule ID, rule-linked evidence, severity level, confidence score, suggested corrective action** |
| | Audit log engine | **10** | Append-only, tamper-evident, replayable history |
| **Phase 2** — due 20 Oct 2026 | Detection quality & benchmark | **15** | **Macro F1 on the 50-claim validation dataset**; high Macro F1 across rule categories; preserve valid claims / low false-positive rate |
| | Human-in-the-loop & escalation | **10** | Flag low-confidence or high-severity findings for **explicit human approval**; manual overrides; feedback logging |
| | Privacy, security & safety guards | **5** | Data minimization; access control; prompt/data security guards preventing hallucinated clinical advice; graceful error handling for malformed FHIR |
| **Phase 3 (selection gate)** — due 1 Nov 2026 | Quality of interface / usability | **10** | Human-review interface presenting findings, rule evidence, severity; interactive approval/override controls |
| **Phase 4 (finals)** — 14–15 Nov 2026 | Pitch deck, live demo, Q&A | **10** | Pitch ≤ 2 members, English only, 12 min = 5 presentation + 2 live demo + 5 Q&A |
| | **Base total** | **100** | |

### 3.2 Bonuses, penalties, extras

| Item | Points | Notes |
|---|---|---|
| Multi-format attachment parsing (OCR/RAG for PDF clinical notes) | **+2** | FR-100/FR-023; our B3 (vision) + B1 (LLM) slice |
| Dynamic payer-rule management GUI/API | **+2** | FR-101/FR-075 |
| Active learning feedback loop from human overrides | **+2** | FR-102/FR-036 |
| Cryptographic / local-ledger audit log security | **+2** | FR-103/FR-051 |
| Real-time async streaming REST/WebSocket API | **+2** | FR-104/FR-091 |
| Mixed study levels in the team | **+5** | Team of 3–5; +5 if levels are mixed — registration-time fact, must be documented at signup |
| Late submission (any gate) | **−5** each late gate | Non-negotiable calendar: §5 |
| Optional creative bonus (finals pitch) | **+12** | Optional add-on to the 10-pt pitch — R4.4 |
| **Maximum achievable total** | **127** | 100 base + 10 bonuses + 5 mixed levels + 12 creative, with zero late penalties |

**Planning stance:** bonuses are scheduled **only after** the MUST/SHOULD of the phase is green (`06` §11.6 rule: "a bonus must never jeopardize a MUST"). Realistic target for the team: **100 + 5 (mixed) + 2–6 bonus** → 107–111, with the creative pitch (+12) pursued only if the core deck is fully rehearsed. The −5 late penalty is treated as a hard risk: each gate has a cut set with a "soft freeze" 48 h early (see §5).

---

## 4. The traceability matrix — the acceptance checklist

**How to read:** every row is a scored or evaluated requirement. `Spec ref` points to the numbered requirement in `06` (FR/NFR/UC, recette R1.x–R4.x, deliverable D1–D27), `07` (EPIC/task ID), or `05`. `Evidence artifact` is the concrete thing a jury member (or the lead, at each gate) can open to verify the row. **Status** is checked off gate by gate; a row is only "Done" when its evidence artifact exists and is demonstrated. This matrix is the mechanical acceptance checklist for §10 recette in `06`.

### 4.A Scoring rows — every point

| Requirement (near-verbatim from the challenge) | Scoring item | Pts | Our component/feature | Spec/doc reference | Evidence artifact | Status |
|---|---|---|---|---|---|---|
| Deliver a system that ingests and normalizes synthetic healthcare claim data | Phase 1 — Data ingestion & normalization | 15 | Ingest gateway: FHIR R4 JSON + CSV intake, bundle reference resolution, ENV-001 fail-closed envelope, sealed canonical claim package; LLM-assisted free-text normalization (bounded) | FR-001…FR-008 (06 §5.A); ING epic (07); canonical model + DDL (05) | Intake E2E on the 13 fixtures via both FHIR and CSV paths; canonical-package diff JSON; recette R1.1–R1.3 green | ☐ |
| Include a deterministic + AI rule engine that catches administrative problems | Phase 1 — Deterministic + AI rule engine | 15 | Versioned rules-as-data catalogue (YAML + CEL) executing the merged table (§2.4); LLM at edges only (never rule outcomes); fixture regression suite | FR-010…FR-018 (06 §5.B); RUL epic (07); rule YAML schemas (05) | Catalogue manifest v1 (hash-pinned); per-rule unit tests; CLM-0042 emits exactly COV-001 (0.99), AUTH-004 (0.96), DUP-002 (0.88) — recette R1.4–R1.7 | ☐ |
| Produce explainable structured output: findings must contain Claim ID, Rule ID, rule-linked evidence, severity, confidence, and suggested corrective action | Phase 1 — Explainability & structured output | 10 | Finding output contract (7 fields + traceability metadata); evidence-first JSON-Pointer resolution (100% resolve in code); grounded LLM narrative written after rules fire | FR-017, FR-015, FR-020…FR-022 (06 §5.B/§5.C); LLM epic (07) | Schema-validated findings on every fixture; narrative citations 100% resolve; adversarial ungrounded-citation test passes — recette R1.6–R1.9 | ☐ |
| Keep an auditable history of what was checked and recommended | Phase 1 — Audit log engine | 10 | Append-only Postgres (GRANT-locked SELECT+INSERT), SHA-256 hash chain, nightly verification, OTel per-claim trace, decision replay | FR-050…FR-056 (06 §5.F); AUD epic (07) | DB-privilege test; tamper test → broken-link report; replay of ≥ 5 claims reproduces findings — recette R1.10–R1.13 | ☐ |
| Achieve high Macro F1 across rule categories on the 50-claim validation dataset, preserving valid claims with a low false-positive rate | Phase 2 — Detection quality & benchmark | 15 | Evaluation harness over the 50-claim set; per-family Macro F1; clean-claim FP rate; calibration (self-consistency → semantic entropy → Platt/isotonic → conformal α=0.05); seeded mutation generator for extra coverage | FR-080…FR-083, FR-030…FR-035 (06 §5.D/§5.I); CAL/EVL/DAT epics (07); benchmark generator design (05) | Versioned benchmark report with Macro F1, per-family F1, ECE, AUROC, FP rate; targets Macro F1 ≥ 0.90, FP ≤ 5% (cible projet — NFR-003/004) — recette R2.1–R2.4, R2.13 | ☐ |
| Flag low-confidence or high-severity findings for explicit human approval; support manual overrides and feedback logging | Phase 2 — Human-in-the-loop & escalation | 10 | HITL router (enum state machine): 3 tiers; conformal abstention → human; mandated topics (AUTH-004/006/009, ENC-001, eligibility/benefit) **never** confidence-gated; reason-coded overrides; re-review with diff | FR-040…FR-046 (06 §5.E); HIT epic (07) | Routing tests at confidence 0.10 and 0.99 (mandated still reaches human); override records with reason-code enums; re-run diff view — recette R2.5–R2.8 | ☐ |
| Apply privacy, security & safety guards: data minimization, access control, guards preventing hallucinated clinical advice, graceful handling of malformed FHIR | Phase 2 — Privacy, security & safety | 5 | Presidio de-identification (pre-prompt + post-response); RBAC; clinical-refusal contract; attachments as data-not-instructions (injection-inert); structured error envelope; synthetic-only enforcement | FR-060…FR-067, FR-093 (06 §5.G/§5.J); SEC epic (07) | PII-injection test set (0 residual); adversarial attachment payloads inert; clinical prompts refused; fuzz corpus → no 5xx — recette R2.9–R2.12, R1.14 | ☐ |
| Provide a usable human-review interface presenting findings, rule evidence, severity, and interactive approval/override controls | Phase 3 — Interface / usability | 10 | Reviewer UI: intake, claim detail, finding cards with evidence chips, tiered queue, decision dialog with reason codes, rule-catalogue admin, audit viewer, eval dashboard + a11y/ergonomics | FR-070…FR-078 (06 §5.H); UI epic (07) | End-to-end walkthrough on real API data (no mock mode); timed T1 script: CLM-0042 ≤ 3 min, ≤ 3 clicks/decision; WCAG-AA check — recette R3.1–R3.8 | ☐ |
| Pitch deck, live demo and Q&A | Phase 4 — Finals | 10 | Pitch ≤ 2 members, English, 12 min = 5 + 2 + 5; offline live demo (13-fixture script); Q&A defense grounded in the benchmark report | §11.5 D24–D27 (06); DEL epic (07) | Rehearsed dry-run with a mentor; demo ×3 at venue conditions; every deck number matches the versioned report — recette R4.1–R4.5 | ☐ |
| Multi-format attachment parsing (OCR/RAG for PDF clinical notes) | Bonus | +2 | Attachment ingest: OCR + RAG chunking + kind classification; text treated as data-not-instructions | FR-100, FR-023, FR-061 (06 §5.K/§11.6); BON epic (07) | OCR/RAG pipeline demo on fixture PDFs; classification accuracy ≥ 90% on labeled subset (cible projet) | ☐ |
| Dynamic payer-rule management GUI/API | Bonus | +2 | Rule catalogue admin UI + `GET/POST /rules` API with dry-run and hash-pinned publish | FR-101, FR-075 (06 §5.K); BON epic (07) | Admin script: edit → validate → dry-run → publish, audited (UC-05); recette R3.4 | ☐ |
| Active learning feedback loop from human overrides | Bonus | +2 | Overrides feed a labeled buffer; job proposes threshold/rule updates; nothing applied without admin approval | FR-102, FR-036 (06 §5.K); BON epic (07) | Demo over ≥ 20 reason-coded overrides → candidate list with expected Macro F1 impact | ☐ |
| Cryptographic / local-ledger audit log security | Bonus | +2 | SHA-256 hash chain + anchored head in a second location + nightly verify; (local-ledger option documented in ADR) | FR-103, FR-051/052 (06 §5.K) | Hash-chain verify report with anchored head; tamper-detection demo | ☐ |
| Real-time async streaming REST/WebSocket API | Bonus | +2 | Long validations stream phase progress + live findings over WebSocket/SSE | FR-104, FR-091 (06 §5.K) | Subscriber demo: phase-ordered events, terminal event carries report ID | ☐ |
| Team of 3–5 with mixed study levels | Team bonus | +5 | Team composition (5 members, mixed levels) fixed at registration | §12.1 M0, D1 (06); 08 (team doc) | Registration record showing member levels; claimed at signup, not later | ☐ |
| Late submission penalty | Penalty | −5 | Soft-freeze 48 h before every gate; cut set defined | §5 calendar; M0–M4 (06) | Gate checklist signed off before deadline; calendar alarms | ☐ (must never fire) |
| Optional creative bonus pitch | Finals extra | +12 | Creative add-on to the core pitch; pursued only after core deck rehearsed | R4.4, D26 (06) | Mentor-reviewed creative segment in dry-run | ☐ |

### 4.B Velodoc evaluation criteria — every criterion (slides 12–13)

| Requirement | Criterion | Pts | Our component/feature | Spec reference | Evidence artifact | Status |
|---|---|---|---|---|---|---|
| "Find real problems — Do not miss important issues" | Detection recall | (inside 15-pt detection) | Fixture-backed rule coverage (§2.4); per-family recall in the harness; mutation-expanded corpus | FR-013, FR-081, FR-083; R2.1 | Benchmark report: macro + per-family recall; zero missed fixture findings | ☐ |
| "Avoid false alarms — Do not flag everything" | Precision / false positives | (inside 15-pt detection) | Deterministic rules (confidence 1.0 where it matters); CLEAN-001 informational (no alarm); clean-claim FP rate ≤ 5% (cible projet) | FR-016, FR-082; R2.2 | FP report on CLM-0175 + clean mutants; FP ≤ 5% | ☐ |
| "Explain itself — Show why a finding exists" | Explainability | (inside 10-pt explainability) | Evidence-first findings (resolving pointers); grounded narrative; finding-card evidence chips with deterministic trace excerpt | FR-015/017/020–022; R1.7–R1.9 | Every finding's pointers resolve; RAGAS faithfulness on narratives; UC-04 script | ☐ |
| "Know when to ask for help — Use human review appropriately" | Escalation | (inside 10-pt HITL) | Conformal abstention (α=0.05) → HITL; mandated topics never confidence-gated; LLM_UNRELIABLE as first-class task | FR-033/040/041/042, FR-024; R2.4–R2.5 | Abstention-routing audit; mandated-topics test at conf 0.10 and 0.99 | ☐ |
| "Be traceable — Record what happened" | Traceability | (inside 10-pt audit) | Append-only hash chain; per-claim OTel trace; replay + diff; pointers-not-PHI export | FR-050–055; R1.10–R1.13 | Chain verify OK; replay reproduces findings; audit export contains no PHI (FR-056) | ☐ |
| "Be usable — Help someone understand and act" | Usability | (inside 10-pt UI) | 8-screen reviewer UI; reason-code decision dialog; low-click paths; WCAG-AA; demo-mode reproducibility | FR-070–078; R3.1–R3.8 | Timed T1 script ≤ 3 min / ≤ 3 clicks per decision; a11y scan passes | ☐ |

### 4.C The six mission verbs — each mapped to its acceptance evidence

| Verb | Capability | Acceptance | Spec reference | Evidence artifact | Status |
|---|---|---|---|---|---|
| **READ** | Ingest + Normalize understand the synthetic claim package | All 13 fixtures parse (FHIR and CSV paths) into one canonical package; references resolve (R11); ENV-001 stops safely | FR-001–005; R1.1–R1.3 | Intake E2E + canonical diff; ENV-001 stop-scenario trace (no LLM span) | ☐ |
| **CHECK** | Look for administrative problems and inconsistencies | Every fixture rule fires with the published rule ID, severity, and confidence; clean fixture yields zero alarms | FR-010–018; R1.4–R1.5 | Fixture regression run; CLM-0042 JSON diff | ☐ |
| **EXPLAIN** | Show why something was flagged and what evidence supports it | Every finding carries rule-linked evidence; narrative cites only fired rules with resolving pointers | FR-015/017/020–022; R1.6–R1.9 | Finding-card screenshot set; adversarial citation test (0 ungrounded accepted) | ☐ |
| **RECOMMEND** | Suggest what should be reviewed or corrected | Every finding ships a `suggested_corrective_action`; the UI pre-fills it in the decision dialog | FR-017/043/074 | Fixture findings all carry non-empty actions; decision dialog prefills | ☐ |
| **ESCALATE** | Ask a human when uncertain or important | Abstentions and mandated topics create human tasks — never silence, never auto-pass | FR-040–042; R2.4–R2.5 | Queue snapshots showing mandated badge + abstention tasks | ☐ |
| **RECORD** | Keep a trace of what was checked and recommended | Every scored event is in the append-only chain; any decision replayable | FR-050–054; R1.10–R1.13 | Audit timeline + replay report + chain verify | ☐ |

### 4.D The eight deliverables (slide 11) — each verified

| Deliverable (slide 11) | Verification | Spec reference | Evidence artifact | Status |
|---|---|---|---|---|
| 1. Receive synthetic healthcare claim data | Fixtures received via API, parsed, canonicalized | FR-001–004 | Intake E2E logs | ☐ |
| 2. Identify administrative claim risks | Fixture-specified risks all detected, none invented | FR-013/FR-081 | Fixture regression report | ☐ |
| 3. Connect findings to a rule or evidence | Rule ID + resolving evidence present on 100% of findings | FR-015/017 | Pointer-resolution check output | ☐ |
| 4. Explain findings clearly | Narratives grounded; RAGAS faithfulness reported | FR-020–022 | Narrative samples + faithfulness score | ☐ |
| 5. Recommend what to review or correct | Corrective actions on all findings | FR-017 | Fixture finding dump | ☐ |
| 6. Escalate uncertain or high-risk situations | Abstention + mandated routing demonstrable | FR-041/042 | Routing test report | ☐ |
| 7. Keep an auditable history | Chain verifiable, replays reproduce | FR-050–054 | Chain-verify + replay reports | ☐ |
| 8. Present findings in a usable interface | 8-screen UI walkthrough | FR-070–078 | Demo video #3 + timed script | ☐ |

### 4.E Guardrail rows — not scored directly, but they protect scored points

| Guardrail | Why it matters | Spec reference | Evidence artifact | Status |
|---|---|---|---|---|
| No adjudication anywhere (no paid/reduced/denied) | Core principle; a violation costs Phase-2 safety points and is disqualifying at the boundary (§6) | FR-064; ADR P3 | Schema grep for adjudicative fields fails on presence; UI walkthrough | ☐ |
| Synthetic-data-only discipline | Challenge rule; also the privacy story | FR-008/066; ADR P8 | CI scan: zero real identifiers; demo-mode banner | ☐ |
| Offline demo mode mandatory | Venue reliability (NFR-006); the demo must never depend on internet | FR-046, NFR-006 | Offline rehearsal ×2 identical runs; recorded LLM cassettes | ☐ |
| Graceful malformed-FHIR handling | Explicit Phase-2 safety point | FR-093, NFR-017 | Fuzz corpus → 0 × 5xx | ☐ |
| Prompts/data guards against hallucinated clinical advice | Explicit Phase-2 safety point | FR-061/062, NFR-019 | Adversarial suites pass | ☐ |

---

## 5. Deliverables calendar — what is due when

Non-negotiable dates (CSTAM schedule; late = −5 pts per gate). **Soft-freeze rule: every gate has a "cut set" frozen 48 h early; the last 48 h are for rehearsal, packaging, and the recette sign-off — never for new features.**

### 5.1 Registration — 5 September 2026 (M0)

| Artifact set | Owner | Notes |
|---|---|---|
| Team registration (5 members, mixed levels → +5 pts) | Lead | Level mix must be stated **at signup**; not claimable later |
| Docs 01–06 (domain, problem+impact, decode, architecture, data model, cahier des charges) | Team | This repo — submission-ready |
| Public repo skeleton: README, license, `docs/` index, challenge-rules checklist | Senior | D1–D4 (`06` §11.1) |

### 5.2 Phase 1 (MVP, 50 pts) — 1 October 2026 (M1)

| Artifact set | Owner | Spec refs |
|---|---|---|
| Source repo (tag `v1.0.0`): ingestion service, rule engine, LLM normalization+explanation, audit engine, fixture regression suite | Core (lead+senior), B1 | D5–D9; FR-001–056 core |
| API docs: Swagger/OpenAPI auto-docs + Postman collection (all 13 endpoints) | Senior | FR-090; D10; 13 endpoints in `05` |
| Baseline benchmark report (fixture-level: findings, severities, confidences, ECE/AUROC scaffold) | B2/Senior | FR-084; D10 |
| Technical report draft + initial architecture & data-flow diagram | Lead | D21 draft; `04` §4 diagrams |
| Demo video #1: intake → findings → handoff on CLM-0042 | Lead | D11 |
| Recette §10.1 (R1.1–R1.18) all green | Team | `06` §10.1 |

### 5.3 Phase 2 — 20 October 2026 (M2)

| Artifact set | Owner | Spec refs |
|---|---|---|
| Confidence & calibration pipeline (self-consistency → semantic entropy → calibration → conformal abstention) | B2 | D12; FR-030–035 |
| HITL routing + review workflow (tiers, mandated escalation, reason-coded overrides, re-review diff) | Core | D13; FR-040–046 |
| Security & privacy hardening (Presidio, injection tests, RBAC, clinical refusal) | Senior | D14; FR-060–067 |
| Evaluation harness on the 50-claim set: Macro F1, ECE, AUROC, FP rate + seeded mutation generator | B2/B3 | D15–D16; FR-080–083 |
| Performance / benchmark report v2 + network/security documentation | Senior | D17; FR-084 |
| Demo video #2: HITL + calibration + audit replay | Lead | D18 |
| Recette §10.2 (R2.1–R2.13) all green | Team | `06` §10.2 |

### 5.4 Phase 3 (selection gate) — 1 November 2026 (M3)

| Artifact set | Owner | Spec refs |
|---|---|---|
| Reviewer UI, 8 screens, end-to-end on real API data | B1/B3 pair | D19; FR-070–078 |
| Rule catalogue GUI + API | B1 (GUI), Senior (API) | D20; FR-075 |
| **Architecture + data-flow diagram (final)** and technical report (final) | Lead/Senior | D21 |
| Final benchmark report (Macro F1 + ECE + AUROC + FP + per-family) | B2 | D21; FR-084 |
| Offline-mode hardening + demo rehearsal kit | Core | D22; FR-046, NFR-006 |
| Demo video #3 (full product walkthrough) + selection-gate submission | Lead | D23 |

### 5.5 Finals — 14–15 November 2026 (M4)

| Artifact set | Owner | Notes |
|---|---|---|
| Pitch deck — ≤ 2 presenters, English, 12 min = 5 presentation + 2 live demo + 5 Q&A | Lead + 1 presenter | D24; R4.2 |
| Live demo environment: laptop + offline stack, fixtures, recorded cassettes | Senior | D25; R4.1 |
| Optional creative-bonus pitch (+12) | Lead | D26; only if core deck rehearsed |
| Source repo frozen at demo tag; all reports exported | Senior | D27; R4.5 |

---

## 6. Hard constraints and boundaries — non-negotiables

These are **not** engineering preferences; they are the conditions under which the product is legal, challenge-eligible, and defensible. Crossing them is treated as a release-blocking defect and, at the clinical boundary, **a disqualifier rather than a point loss**.

| # | Constraint | What it forbids | Where enforced |
|---|---|---|---|
| 1 | **Synthetic data only** | Real patient data anywhere — repo, fixtures, demos, audit, screenshots | FR-008/066 (CI scan, demo-mode banner); ADR P8; `06` §3.2 |
| 2 | **FHIR R4 JSON and/or CSV only** | XML, EDI 837, proprietary formats in v1 | FR-001/002; `06` §7.1 |
| 3 | **Review, don't adjudicate** | Approving, denying, adjusting, or recommending a payment outcome | FR-064 (schema grep + UI copy); `04` P3; API has no adjudication field |
| 4 | **Never clinical advice** | Diagnosis, treatment recommendation, medical-necessity judgment, "should this claim be approved" answers | FR-062 (refusal contract at API+UI); LLM system prompt; `04` §6 |
| 5 | **No real member records** | Any real person's identifier, name, or PHI in any artifact | FR-060/066 (Presidio + guard); pointers-not-PHI audit export (FR-056) |
| 6 | **Human stays accountable** | An autonomous loop deciding anything consequential; the override is a human act with a reason code; the system is a copilot, not an autonomous payer (veloclaim.app FAQ, verbatim: *"ClaimGuard is a copilot, not an autonomous payer; accountability stays with people."*) | FR-040–043 (three tiers, reason codes, RBAC); `04` §6 (LLM never routes, never overrides, never edits the package) |

### Regulatory reasoning (design boundaries, not product claims)

1. **US — FDA Clinical Decision Support (CDS).** Software that merely administers claims is not a medical device; the closer a tool gets to the clinical lane, the more the FDA's CDS criteria apply — in particular the requirement that the software *"enable the healthcare professional to independently review the basis for… recommendations"*, so the HCP remains the decision-maker. ClaimGuard stays administrative-only and its evidence-first findings (every signal cites a resolving JSON Pointer the reviewer can open) are, structurally, the "independently review the basis" property — but we do **not** rely on exemptions: we simply never produce clinical output. (Source: https://recovry.ai/news/the-emerging-third-lane-of-healthcare-ai)
2. **EU — AI Act.** The Annex III high-risk insurance category (item 5(c)) covers *life and health insurance risk assessment and pricing*; administrative claims **pre-validation** is not risk assessment or pricing, so it is **not** high-risk under the Act. This is a compliance posture statement for the record, not a license to be careless: we still document human oversight, auditability, and transparency because the client operates in a Gulf/international market. (Source: https://actuary.info/insights/eu-ai-act-high-risk-insurance-underwriting-august-2026)
3. **UAE/Gulf — ADHICS.** Abu Dhabi's ADHICS (v2) data standard governs health information exchange and applies to **payers and providers** alike; our posture is data-minimization + de-identification + on-prem/offline deployment, which positions us cleanly under ADHICS-style residency expectations. (Source: https://www.doh.gov.ae/-/media/Feature/Resources/Standards/ADHICS-v2-standard.ashx)

**The boundary, stated plainly:** the instant ClaimGuard outputs a diagnosis, a treatment recommendation, a medical-necessity judgment, or a payment decision, it ceases to be the challenge's "quality gate / copilot" and becomes an unvalidated, unregulated clinical or adjudicative system. That is a disqualifier, not a point deduction. FR-062/FR-064 + the LLM refusal contract are enforced by tests, and the lead reviews every demo script against this boundary.

---

## 7. What is NOT required — the anti-scope list

The competition does not ask for a production claims platform. Anything on this list that the team builds anyway is gold-plating that consumes beginner-hours and risks the MUSTs (`06` §11.6 rule). The lead rejects scope violations on sight.

| # | NOT required | Why not | If we ever touch it |
|---|---|---|---|
| 1 | **Real payer integration** (EDI 837/835, eClaimLink, payer APIs) | Synthetic-only challenge; no production connectivity | Never in v1–v3 (`06` §3.2 #1) |
| 2 | **Real EMR/EHR integration** | No real clinical systems; inputs are files | Never in v1–v3 (`06` §3.2 #2) |
| 3 | **Production PHI / real member records** | Challenge rule + regulatory boundary | Never, ever (FR-066) |
| 4 | **Payment processing** (submission, remittance, adjudication) | We are the gate *before* submission; ClaimGuard never submits, never talks to the payer | Never (FR-064; `04` §3 boundary table) |
| 5 | **Multi-tenant SaaS** (customer onboarding, billing, SLAs, multi-org isolation beyond RBAC) | Challenge horizon; single deployment | Post-event only (NFR-006/011) |
| 6 | **Mobile app** | Desktop-web UI only; mobile is a bonus-shaped extra, not a requirement | WON'T unless taken as bonus (FR-105) |
| 7 | **Autonomous adjudication / auto-approve** | The opposite of the mission ("Built for review, not replacement") | Forbidden by design (FR-064, ADR P3) |
| 8 | **Autonomous agent loops in the decision core** (CrewAI/AutoGen-style) | Replayability + audit + "know when to ask for help" all require a deterministic core | Rejected at ADR level (`04` §2 P1); LangGraph only as a later upgrade path |
| 9 | **Custom LLM training / fine-tuning** | Out of scope; prompting + structured output + calibration is the lever | No; the calibration pipeline (FR-030–035) is the ML slice |
| 10 | **Clinical decision support of any kind** | Regulatory disqualifier (see §6) | Forbidden by contract (FR-062) |

---

## 8. Open questions for the mentors (Dr. Wael Hilali, Bilel Said)

Sharp, grading-intent questions to settle before Phase 2 planning locks. Each is phrased so the answer changes our plan.

1. **The 50-claim validation dataset: is it provided by the organizers or must we build it?** If provided: when is it published, in what format (FHIR JSON / CSV / both), and does it use the same 13-fixture rule IDs or the R01–R15 numbering? If we must build it: may we publish our construction methodology (seed, mutation spec) as part of the benchmark report, and is an organizer-reviewed label set available for cross-checking?
2. **How is Macro F1 computed — per rule family or per individual rule?** The published scoring note ("balances precision and recall across finding types") is ambiguous: if it is per-family, our 6-family grouping is right; if per-rule, adding rules (AUTH-009, COV-008, our ADDED rules) changes the metric surface and we may want a leaner catalogue. A worked example with 2–3 families and 2–3 rules would settle it.
3. **May we extend the fictional rule catalogue beyond R01–R15?** The fixtures already ship rules (COV-008, AUTH-009, INT-003, ENC-001, ENV-001…) that do not exist in R01–R15. Confirming we may keep and extend the fixture rule IDs, and that our ADDED rules are scored as legitimate findings, affects §2.4 directly.
4. **Is there a preferred LLM provider, or must the system run offline/local?** We plan an OpenAI-compatible client with an Ollama/vLLM profile for the mandatory offline demo. Is a hosted API during the event acceptable if the demo is fully recorded, or should we assume no internet at Hammamet?
5. **What does the mandatory mentoring session format expect — a progress checkpoint, a worksheet, or a demo?** Knowing whether mentors grade on artifact completeness at each session (and whether attendance affects advancement, as the general rules suggest) determines how we time the working sessions.
6. **How is the +12 "creative bonus" judged?** Is it a separate rubric, a multiplier, or a jury-discretion item? Would a live role-play of the HITL escalation ("reviewer versus system") be an eligible creative direction, or is it expected to be a product/demo presentation as well?
7. **Are the Phase-2 datasets and Phase-1 fixtures the same catalogue version?** If the benchmark reuses catalogue v1 rules, our fixture regression suite doubles as benchmark prep; if the benchmark may include novel rule types (e.g., R13 service location, R04 procedure support), we need the plan tables early.
8. **Is the leaderboard or jury feedback shared between Phase 2 and the Phase 3 selection gate?** If yes, we will time the final catalogue tuning (ADDED vs DEFERRED rules in §2.4) to that feedback.

---

## Appendix — Source register

| Claim | Source |
|---|---|
| Six mission verbs (slide 09); "Six plain-language verbs. No architecture prescription…"; "Built for review, not replacement" | veloclaim.app (2026) |
| Rules + AI + Humans = trustworthy copilot (slide 10); "Teams are free to choose their preferred technical approach" | veloclaim.app (2026) |
| Eight deliverables (slide 11); callout text | veloclaim.app (2026) |
| Six evaluation criteria (slides 12–13); Macro F1 scoring notes verbatim | veloclaim.app (2026) |
| R01–R15 fictional rule catalogue | veloclaim.app/reference (2026) |
| 13 synthetic fixtures, rule IDs, confidences, evidence paths, reviewNotes | Challenge fixtures via veloclaim.app (2026) |
| Phase scoring (50/30/10/10), bonus +2 items, +5 mixed levels, −5 late, pitch format, rewards | CSTAM Book pp. 17–19 (2026) |
| FDA CDS / "independently review the basis" rationale | https://recovry.ai/news/the-emerging-third-lane-of-healthcare-ai |
| EU AI Act Annex III 5(c) — claims processing not high-risk | https://actuary.info/insights/eu-ai-act-high-risk-insurance-underwriting-august-2026 |
| ADHICS v2 (Abu Dhabi) — payers and providers | https://www.doh.gov.ae/-/media/Feature/Resources/Standards/ADHICS-v2-standard.ashx |
| RFC 6901 JSON Pointer | https://www.rfc-editor.org/rfc/rfc6901 |

**Version history:** v1.0 — 2026-09-04 — initial issue, aligned with docs 01–08. Next revision: after mentor answers to §8.