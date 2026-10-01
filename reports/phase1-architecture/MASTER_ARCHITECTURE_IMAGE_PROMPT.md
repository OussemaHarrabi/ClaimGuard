# ClaimGuard master architecture image prompt

Use the full prompt below in an image-generation system capable of producing precise, high-resolution technical diagrams. The output must be a single professional landscape architecture plate that can be inserted as a full-width or rotated page in an A4 engineering report.

## Copy-ready prompt

Create a publication-quality enterprise software architecture diagram titled:

**"ClaimGuard - Evidence-First Healthcare Claim Pre-Validation Architecture"**

The diagram represents a synthetic-data healthcare insurance claim review platform built by **Team Claimix**. It must look like a serious system architecture figure for an academic and engineering report, not like a marketing infographic, presentation slide, mind map, or generic AI-generated flowchart.

### 1. Output format and visual quality

- Produce one ultra-high-resolution landscape image, ideally 7680 x 4320 pixels or a true editable vector equivalent.
- Use a clean white or very light blue-grey background, generous margins, a fine alignment grid, sharp vector lines, and readable typography.
- Use an A3-landscape or 16:9 composition that remains readable when placed on an A4 landscape page.
- Use a modern professional typeface similar to Inter, IBM Plex Sans, Source Sans 3, or Segoe UI.
- All labels must be spelled exactly as provided. Do not invent acronyms, product names, cloud providers, APIs, protocols, or database technologies.
- Keep visual depth subtle. Use very light shadows, 8 to 12 px corner radii, consistent internal padding, and thin 1.5 to 2 px connectors.
- Use orthogonal connectors with arrowheads. Prevent line crossings. Every arrow must have a concise semantic label.
- Do not render paragraphs inside nodes. Use short headings plus one compact supporting line.
- Make the most important path visually dominant from left to right.
- Add the ClaimGuard shield and checkmark logo in the upper-left corner. Use a navy shield with a cyan-teal checkmark and two small evidence lines. Place the wordmark **ClaimGuard** beside it, with "Claim" in navy and "Guard" in teal.
- Add a small subtitle below the title: **"Review before submission. Explain with evidence. Keep the human in control."**
- Add a small footer: **"Team Claimix | Synthetic data and fictional payer rules | Pre-submission review, not adjudication"**.

### 2. Colour system

Use the following semantic palette consistently:

- Deep navy `#102B49`: titles, identity, core boundaries, authoritative labels.
- Teal `#0A9CA8`: user experience and accepted service paths.
- Green `#0D9B72`: deterministic processing and successfully validated data flow.
- Violet `#7C3AED`: PostgreSQL, persisted records, version history, and audit data.
- Rose red `#E72C57`: security gates, rejected model output, quarantine, prohibited actions, or failures.
- Amber `#D88900`: work in progress and future components.
- Slate `#5B6F82`: human actions, metadata, operational paths, and secondary connectors.
- Very light tinted fills derived from the relevant border colour. Keep text dark and accessible.

### 3. Overall layout

Organize the plate into six clearly labelled vertical zones arranged from left to right. Each zone should be a large rounded container with a small numbered heading at its top. Show the main runtime path through the middle. Show optional or supporting paths above it. Show persistence and audit paths below it.

The six zones are:

1. **Clinic Users and Sources**
2. **Experience and Access Control**
3. **Ingestion and Normalization**
4. **Deterministic Validation Core**
5. **Guarded Assistance and Human Review**
6. **Versioned Data and Audit**

Behind zones 2 through 6, add one broad dashed boundary labelled **"ClaimGuard application boundary"**. Around all database elements, add a second violet dashed boundary labelled **"PostgreSQL 16 - tenant-owned records"**.

### 4. Zone 1 - Clinic Users and Sources

At the far left, show two stacked groups.

#### User roles

Use four compact user cards with simple line icons:

- **RCM Reviewer** - reviews assigned findings, requests information, corrects and rechecks.
- **RCM Lead** - assigns work, handles escalations, monitors review quality.
- **Clinic Admin** - manages clinic staff, departments, routing, analytics, and audit views.
- **Technical Manager** - sees health, versions, redacted logs, intake jobs, and integrity status, but never claim contents.

Group these cards inside a container labelled **"One clinic tenant"**. Add a small note: **"Departments and memberships are clinic-scoped"**.

#### Synthetic source packages

Below the users, show three source-document cards:

- **ClaimGuard JSON envelope** - complete 17-key synthetic claim.
- **Relational CSV package** - patient, coverage, provider, diagnosis, claim lines, authorizations, attachments.
- **FHIR R4 Bundle + verified sidecar** - partial FHIR projection plus sidecar fields required by the scoring contract.

Add an amber dashed future source card:

- **Clinical documents - future** - synthetic dental report, invoice, pre-authorization, notes, images or PDF; extraction not yet authoritative.

Add a rose security label underneath all sources: **"Untrusted input: data only, never instructions"**.

### 5. Zone 2 - Experience and Access Control

Show a large teal component:

- **Next.js 16 Workspace**
  - Sub-label: **"React 19, TypeScript, shadcn and Radix UI"**
  - Small internal page chips: **My Queue**, **Team Queue**, **Document Intake**, **Claim Workspace**, **Assignments**, **Analytics**, **Audit**, **Operations**.

Above or beside it show:

- **Signed Session and Role Gate**
  - Sub-label: **"8-hour HttpOnly, SameSite=Strict session"**
  - Show four role badges matching the four clinic roles.
  - Show **tenant_id** and **user_id** being derived from the session, never accepted from request bodies.

Show a FastAPI gateway component after the role gate:

- **FastAPI Service**
  - Sub-label: **"Tenant-scoped REST API under /v1"**
  - Small route groups: **auth**, **claims and runs**, **queue and decisions**, **intake**, **clinic administration**, **operations**, **assistant**.

Connect users to Next.js with an arrow labelled **"browser actions"**. Connect Next.js to FastAPI with **"HTTPS or local HTTP, JSON, session cookie"**. Connect the role gate to all protected API routes with **"authenticate, authorize, scope"**.

Show a rose shield boundary across this zone labelled:

**B1 - Identity and tenant boundary: frontend navigation is guidance; API and storage filters enforce access.**

Add one explicit prohibition marker beside the Technical Manager route:

**"No claim envelopes, findings, or patient content"**.

### 6. Zone 3 - Ingestion and Normalization

Create a visually ordered intake pipeline with the following nodes:

1. **Format Detector**
   - Detects JSON envelope, relational CSV package, or FHIR Bundle plus sidecar.
   - Does not guess an incomplete format.

2. **Intake Adapters**
   - Three small internal adapter blocks labelled **JSON**, **CSV**, **FHIR + sidecar**.
   - CSV rebuilds the structured envelope.
   - FHIR-projected paths are compared with the verified sidecar before acceptance.

3. **Transport Validator**
   - Exact 17-key top-level contract.
   - Type and shape validation.
   - Missing or malformed information is not invented.

4. **Quarantine / Rejected Intake**
   - Rose node below the transport validator.
   - Label: **"structured ingestion error, reason code, no rule execution"**.

5. **Canonical Scoring Envelope**
   - Green or navy data object.
   - Label: **"17-key normalized claim contract"**.
   - Show small data tags: claim identity, patient and member, provider and payer, diagnosis, coverage, lines, authorizations, attachments, totals, dates, currency, notes.

6. **Intake Job Record**
   - Violet side node.
   - Label: **"source type, SHA-256 digest, validation state, optional run link"**.
   - Make clear that raw source text is not retained by the current JSON intake pilot.

Connect the three source packages to Format Detector using separate arrows labelled **"synthetic source package"**. Connect Format Detector to Intake Adapters with **"classified payload"**. Connect Intake Adapters to Transport Validator with **"candidate envelope"**. Connect successful validation to Canonical Scoring Envelope with **"validated fields"**. Connect validation failure downward to Quarantine with **"reject and explain"**. Connect all intake outcomes to Intake Job Record with **"record state and digest"**.

Place a rose dashed trust boundary across the source-to-validator transition:

**B2 - Claim-data boundary: invalid input stops here; no default or missing clinical fact is invented.**

Add a small amber note near FHIR:

**"Current limit: FHIR alone does not supply every scoring field. Encounter is not retained in the 17-key scoring envelope."**

### 7. Zone 4 - Deterministic Validation Core

This zone must be visually dominant and labelled **"Authoritative decision path - no model and no network"**.

Show the following components:

1. **Versioned Fictional Payer Rule Catalogue**
   - Sub-label: **"rules, policies, services, providers, diagnoses"**.
   - Version badge: **"1.0.0"**.
   - Show rules **R001 through R015** as a compact grid of fifteen small numbered chips.

2. **RuleContext Resolver**
   - Resolves the policy and rule metadata.
   - Unknown policy is not replaced by an invented default.

3. **Deterministic Rule Engine**
   - Large green core node.
   - Label: **"evaluate exactly 15 checks per accepted claim"**.
   - Show the five possible statuses in small chips:
     **PASS**, **FAIL**, **UNABLE_TO_ASSESS**, **NOT_APPLICABLE**, **NOT_IMPLEMENTED**.
   - Add a small note: **"FAIL precedes uncertainty; uncertainty precedes pass or not applicable"**.

4. **Evidence Resolver**
   - Label: **"RFC 6901 path plus exact value from the original envelope"**.
   - Show a small example object: `{ path: "/lines/0/net_amount", value: 150.00 }`.

5. **Structured Result Assembler**
   - Label: **"one frozen 15-key record per rule"**.
   - Show compact key groups: Claim ID, Rule ID and version, status, severity, affected lines, evidence, rule source, explanation, corrective action, confidence, human-review flag, method, review status.
   - Add: **"confidence = null; confidence_kind = not_probabilistic"**.

6. **Run Summary**
   - Counts by status, needs-attention flag, duplicate indicator, rule and prompt versions, input hash.

Connect Canonical Scoring Envelope to RuleContext Resolver and Deterministic Rule Engine. Connect Rule Catalogue to RuleContext Resolver with **"versioned policy context"**. Connect the engine to Evidence Resolver with **"rule outcome and affected paths"**. Connect Evidence Resolver to Result Assembler with **"re-resolved evidence"**. Connect Result Assembler to Run Summary with **"15 result records"**.

Add a thick navy-green border around the entire zone with the label:

**B3 - Authority boundary: only deterministic rules establish status, severity, evidence, and whether human review is required.**

### 8. Zone 5 - Guarded Assistance and Human Review

Divide this zone into an upper optional AI lane and a lower human workflow lane.

#### Upper lane - bounded explanation and assistant

Show a graph-shaped chain with these nodes, in this order:

1. **Scope Guard** - deterministic positive grounding; refuses decision requests, clinical advice, injection attempts, and off-topic questions before any model call.
2. **Gather Read-Only Context** - stored finding, cited evidence values, rule text, policy limits, and current conversation only.
3. **Draft** - optional SLM or model call.
4. **Verifier** - exact five-key schema, citation re-resolution, allowed rule IDs, prohibited assertions, injection and echo guards.
5. **Repair Once** - optional single bounded redraft using rejection reasons.
6. **Deterministic Fallback** - always available when model is off, unavailable, malformed, unsupported, or rejected.
7. **Finalize Answer** - explanation, correction recommendation, citations, human-review flag, model and prompt provenance, verification state, latency, SHA-256 receipt.

Show a small external node above Draft:

- **Optional Model Provider**
  - Label: **"off by default; evidence subset only"**.
  - Connect using a dashed rose arrow labelled **"one bounded HTTPS request when configured"**.

Show three verifier outcomes:

- Green arrow **"accepted"** from Verifier to Finalize Answer.
- Amber arrow **"rejected, one attempt left"** from Verifier to Repair Once, then back to Verifier.
- Rose arrow **"rejected again or provider unavailable"** from Verifier to Deterministic Fallback, then to Finalize Answer.

Place a large rose security label around this lane:

**B4 - AI authority boundary: model text can clarify and recommend. It cannot change a rule status, severity, evidence pointer, routing decision, claim field, reviewer decision, or audit record.**

Add a small separate amber dashed component:

- **JEV Advisory Sidecar - evaluated next**
  - Label: **"grounding, agreement, attention signal only"**.
  - Show no arrow into the authoritative result record.
  - Use an amber dotted arrow to a small evaluation box labelled **"latency, quality, failure and privacy benchmark"**.

#### Lower lane - reviewer workflow

Show these nodes:

1. **Evidence Desk** - finding, original values, applicable rule, explanation provenance, and correction recommendation on one aligned row.
2. **Reviewer Decision** - four allowed actions only:
   - confirm issue
   - dismiss with reason
   - request information
   - mark corrected for recheck
3. **Correction Editor** - guided fields with human-readable labels and the source evidence beside the suggested change.
4. **Recheck** - creates a new claim version and a new deterministic run; never overwrites the original.
5. **Assignment, Request and Escalation** - lead or admin routes work within the same tenant.

Connect Run Summary and Structured Result Assembler to Evidence Desk with **"finding plus evidence and provenance"**. Connect Finalize Answer to Evidence Desk with **"verified explanation or labelled fallback"**. Connect Evidence Desk to Reviewer Decision with **"human judgment and reason"**. Connect mark-corrected action to Correction Editor and then back to the Canonical Scoring Envelope in Zone 3 or directly to the Deterministic Rule Engine in Zone 4 using a large loop labelled **"new immutable version, version + 1, supersedes_run_id"**. The loop must never point backward as an overwrite.

Add a navy callout:

**"Review, do not adjudicate: ClaimGuard never approves, denies, prices, pays, diagnoses, or submits a claim."**

### 9. Zone 6 - Versioned Data and Audit

Inside the PostgreSQL boundary, organize tables into four clearly labelled groups. Show table icons, not cylinders for every individual table. Use one database cluster with grouped subpanels.

#### A. Clinic identity and access

- `clinics`
- `users`
- `clinic_memberships`
- `clinic_departments`
- `clinic_configuration`

Key relation labels:

- one clinic to many memberships and departments
- one user to many clinic memberships
- membership carries role and active state

#### B. Claim review and work management

- `rule_runs`
- `rule_results`
- `review_decisions`
- `run_explanations`
- `claim_assignments`
- `clinic_requests`
- `clinic_escalations`
- `intake_jobs`

Key relation labels:

- one run to exactly 15 rule results
- one run to many append-only decisions
- one run to per-rule explanation provenance
- corrected run points to the prior run through `supersedes_run_id`
- every tenant-owned review table carries `tenant_id`

#### C. Interactive assistant

- `assistant_threads`
- `assistant_turns`

Key relation labels:

- one thread per tenant, run, rule, and reviewer
- turns are append-only and ordered by sequence
- assistant records never update `rule_results`

#### D. Audit integrity

- `audit_events`

Inside the table show the important fields as small labels:

- `event_id`, `event_type`, `at`, `actor`, `claim_ref`, `trace_id`
- `payload`, `prev_hash`, `chain_hash`

Show a repeating chain visual: Event N-1 hash to Event N previous hash to Event N hash. Label it **"SHA-256 append-only tamper-evident chain"**.

Connect FastAPI to PostgreSQL with **"parameterized SQL through SQLAlchemy and psycopg"**. Connect Run Summary to `rule_runs` and `rule_results` with **"atomic run write"**. Connect reviewer decisions to `review_decisions`. Connect verified explanation provenance to `run_explanations`. Connect assistant final answers to `assistant_turns`. Connect every run and decision write to `audit_events` with **"append event"**.

Add two integrity labels:

- **"UPDATE and DELETE refused by database triggers on protected records"**.
- **"Tamper-evident, not absolutely immutable: a database owner or superuser remains a production risk."**

Place a violet trust boundary label:

**B5 - Persistence boundary: versioned writes preserve history; tenant predicates prevent cross-clinic reads in the current application layer.**

Add an amber security note:

**"Production hardening next: non-owner runtime role plus database row-level security or equivalent isolation."**

### 10. Operational lane across the bottom

Across the lower edge of zones 2 through 6, add a slim operational rail:

- **OpenTelemetry instrumentation** - FastAPI and SQLAlchemy traces.
- **Structured redacted logs** - no claim content for the Technical Manager.
- **Health and readiness** - API health, database reachability, rule catalogue version, AI mode.
- **Audit integrity check** - verifies the chain without exposing claim contents.
- **Docker Compose local stack** - `web`, `api`, `migrate`, `db`.

Use slate connectors from the service and database to this rail. Do not show Grafana as implemented unless marked clearly as **"future monitoring integration"** with an amber dashed border.

### 11. Numbered end-to-end flow

Place small numbered circles on the primary connectors so the reader can follow one claim:

1. User signs in to the clinic workspace.
2. The signed session resolves user, role, and tenant.
3. Reviewer uploads or submits a synthetic claim package.
4. The format is detected and mapped by the appropriate adapter.
5. The exact 17-key transport contract validates the envelope.
6. Invalid input is quarantined; valid input receives an intake record.
7. The deterministic engine loads the versioned fictional rule context.
8. R001 through R015 produce exactly 15 results.
9. Evidence paths re-resolve against the original envelope.
10. Results, run metadata, and audit event persist atomically.
11. Optional assistance drafts an explanation, then the verifier accepts, repairs once, or falls back.
12. The reviewer reads the issue, evidence, rule, and next step together.
13. A decision is appended, or a correction creates a new claim version and recheck.
14. The audit chain preserves the sequence of run and decision events for replay and integrity verification.

### 12. Legend

Add a compact legend in the lower-right corner:

- Solid green arrow: authoritative deterministic data flow.
- Solid teal arrow: user or application request.
- Solid violet arrow: persistent write or version link.
- Dashed rose arrow: guarded model, security, rejection, or untrusted-data flow.
- Dotted amber arrow: future work or advisory-only component.
- Slate arrow: human action or operational metadata.
- Solid component border: implemented in the current synthetic-data MVP.
- Dashed amber component border: started or planned, not yet authoritative.
- Shield icon: enforced security or authority boundary.
- Database icon: PostgreSQL persisted state.
- Person icon: accountable human action.

### 13. Explicit non-claims and negative constraints

The diagram must not show or imply any of the following:

- No payer submission integration.
- No automated claim approval or denial.
- No autonomous claim correction.
- No clinical diagnosis, treatment recommendation, or medical necessity judgment.
- No real patient data.
- No blockchain.
- No Kubernetes, AWS, Azure, GCP, Kafka, Redis, vector database, or microservice fleet unless explicitly marked as absent. They are not part of the current architecture.
- No model arrow entering the rule engine or changing a rule result.
- No direct model write to claims, findings, decisions, or the audit ledger.
- No implication that FHIR alone currently reconstructs the complete scoring envelope.
- No claim that the hash chain is deletion-proof against a database owner.
- No generic labels such as "AI magic", "smart engine", "big data", or "secure cloud".
- No tiny decorative text, pseudo-code gibberish, fake logos, illegible arrows, crossing connectors, or spelling errors.

### 14. Desired visual reading order

The reader should understand the following story in less than 20 seconds:

1. A clinic user submits structured synthetic claim information.
2. Identity and tenant boundaries protect the workspace.
3. Input becomes one strict normalized envelope or is rejected visibly.
4. Fifteen deterministic rules remain the authority.
5. Every result cites exact source evidence and suggests a correction.
6. AI can explain only through a verifier and safe fallback.
7. A human decides, corrects, or requests information.
8. Corrections create new versions.
9. PostgreSQL preserves runs, decisions, assistant provenance, and a tamper-evident audit trail.

End result: a dense but highly organized architecture plate with the precision of a solution-architecture document, the restraint of a healthcare enterprise system, and the visual polish of a top-tier engineering report.

## Acceptance checklist for the generated image

Before returning the image, verify all of the following:

- The title contains "ClaimGuard" and not another product name.
- The six zones are present and correctly ordered.
- The deterministic engine is visually dominant.
- R001-R015 and the five result statuses are visible.
- JSON, CSV, and FHIR plus sidecar intake are present.
- Quarantine, human review, correction and versioned recheck are present.
- The model is optional and separated from the authoritative path.
- The scope guard, verifier, one repair attempt, and deterministic fallback are present.
- The four user roles and the Technical Manager content restriction are visible.
- PostgreSQL table groups and the audit hash chain are visible.
- Implemented components and future work are visually distinguishable.
- No prohibited production or adjudication claim appears.
- Text remains readable at 100 percent zoom on a 1920 x 1080 display.
