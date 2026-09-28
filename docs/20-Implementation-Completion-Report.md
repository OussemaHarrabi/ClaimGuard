# 20 — Product rebuild completion report

> **Release date:** 2026-09-26
> **Target branch:** `main`
> **Source branch:** `codex/product-rebuild`
> **Scope:** deterministic claim validation, reviewer workflow, Next.js evidence desk, secured SLM
> assistance, JEV advisory experiment, deployment packaging, benchmark methodology and handoff.
> **Posture:** review, do not adjudicate.

## 1. Executive summary

ClaimGuard is now an end-to-end pre-submission review system for the fictional CSTAM/Velodoc claim
contract. It normalizes a claim, runs all fifteen versioned deterministic rules, preserves exact
evidence pointers, creates an immutable review run, exposes findings in a responsive Next.js
cockpit, lets an administrator record bounded decisions or submit a corrected claim as a new
version, and records audit/provenance data separately from the frozen scoring record.

The explanation capability has been upgraded from a prose-only optional rewrite into a secured SLM
assistance contract. For every attention finding, the SLM may draft an explanation and a contextual
correction recommendation. It cannot set status, severity, routing, evidence or a review decision.
Every candidate is checked by a deterministic verifier and receives an `accept`, `fallback` or
`decline` decision plus a SHA-256 receipt. Unsafe, unavailable or malformed output is replaced by a
clearly labelled deterministic safe twin.

The previous Colab results remain preserved, but no model is called deployable. Qwen3 4B BF16 had
the highest raw aggregate score and Gemma 4 E4B Q4 was the strongest next experimental candidate;
both failed at least one hard gate. The benchmark notebook now implements secured contract v2 and
must be rerun before a checkpoint is selected. Fine-tuning is intentionally deferred until a larger,
adjudicated evaluation demonstrates a stable residual error that constrained generation and the
security envelope do not solve.

## 2. Delivered product capabilities

| Area | Delivered behaviour | Primary implementation |
|---|---|---|
| Contract | Exact 17-key claim envelope and frozen 15-key result record | `claimguard/edu/envelope.py` |
| Rules | R001–R015 with five statuses and rulebook precedence | `claimguard/edu/rules/` |
| Evidence | RFC 6901 paths re-resolved against the original envelope | `claimguard/edu/evidence.py` |
| Intake | Authoritative JSONL plus CSV reconstruction and bounded FHIR projection | `claimguard/edu/intake/` |
| Review runs | Immutable versioned runs, results, decisions and corrections | `claimguard/review/` |
| Queue | Counts, filters, unresolved state and claim/run selection | `GET /v1/queue` |
| Decisions | Request information, confirm issue, dismiss with reason, corrected-for-recheck | `POST /v1/runs/{id}/decisions` |
| Correction | Stored-envelope retrieval and new-version recheck | `GET /v1/runs/{id}/claim`, `POST /v1/claims/{id}/recheck` |
| Primary UI | Responsive Next.js evidence desk | `frontend/` |
| SLM assistance | Explanation plus correction recommendation under an exact five-field contract | `claimguard/edu/explain/` |
| Security envelope | Citation verification, invariant checks, injection guards, decisions and receipts | `provider.py`, `verifier.py` |
| JEV | Offline-safe typed advisory second opinion and sidecar | `claimguard/edu/judge/` |
| Audit | Append-only, hash-chained audit events with documented limitations | `claimguard/audit/`, migration `0001` |
| Packaging | Multi-stage API/frontend images and Compose stack | `Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` |
| Evaluation | Mentor scorer, independent conformance harness and generated reports | `scripts/edu_conformance.py`, `scripts/edu_report.py` |

## 3. Runtime architecture and authority boundaries

The operational flow is:

1. A normalized claim enters the API.
2. The deterministic engine evaluates all fifteen rules.
3. The frozen result records are stored as the authoritative run output.
4. Findings with `FAIL`, `UNABLE_TO_ASSESS` or `NOT_IMPLEMENTED` are eligible for bounded SLM
   assistance; `PASS` and `NOT_APPLICABLE` do not need model-generated help.
5. The SLM receives only the finding, selected rule context and supplied evidence. Evidence is data,
   never instruction authority.
6. The deterministic verifier either accepts the candidate or creates the deterministic safe twin.
7. Provenance is stored in `run_explanations`; it never adds keys to the graded result record.
8. The administrator reviews the finding, evidence, assistance and verifier state together.
9. Human actions create decision events. Corrections create a new claim version and a new run.

Authority is deliberately asymmetric:

- the rule catalogue and engine own status, severity, evidence, routing and human-review flags;
- the SLM owns no state and may only draft reviewer-facing language;
- the assistance verifier owns whether model language is displayable;
- JEV may produce a typed advisory sidecar but cannot override the engine or verifier;
- only a human can record a review decision or submit a corrected envelope;
- no explanation, judge output or UI interaction mutates an existing run.

This is the part inspired by the AegisGraph work: explicit authority edges, untrusted-data labels,
fail-closed decisions, evidence-bound outputs, tamper-evident receipts, and measurable security
outcomes instead of a prompt-only claim of safety.

## 4. Next.js frontend rebuild

The old HTML/CSS/JavaScript page remains as a fallback, but the primary product surface is a Next.js
16 reviewer cockpit. It is designed as an evidence desk rather than a chat interface.

### 4.1 Main interaction model

- left: claims queue, counts, search and unresolved state;
- centre: selected immutable run, deterministic findings, evidence and bounded review actions;
- right: explanation, correction recommendation, provenance, security decision, receipt and verifier
  warnings;
- responsive layouts preserve the same information hierarchy at narrower breakpoints;
- the correction drawer retrieves the stored claim, edits synthetic JSON, validates `claim_id`, and
  submits a new version for recheck;
- “Use as editable note” copies a verified recommendation into the administrator's note. It does
  not submit a decision or modify claim data.

### 4.2 Honesty and accessibility details

- model output is labelled “Model-assisted wording”;
- rejected output is labelled “Deterministic fallback”;
- explicitly deterministic output is never presented as SLM-generated;
- security state and receipt prefix remain visible beside provider/model/prompt provenance;
- human-review and non-adjudication boundaries are repeated at the point of use;
- keyboard-labelled controls, semantic headings, evidence regions, reduced-motion support and
  responsive breakpoints are present;
- demo mode is visibly read-only and cannot masquerade as a live API.

`PRODUCT.md` and `DESIGN.md` preserve the product and interface rationale. The rebuild follows the
familiar operational density and calm visual language requested for the Velodoc jury without copying
proprietary assets or creating a deceptive clone.

## 5. Secured SLM assistance contract

### 5.1 Exact model output

The deployed prompt version is `2.0.0`. The model must return exactly:

```json
{
  "explanation": "string",
  "correction_recommendation": "string",
  "cited_evidence_paths": ["/pointer"],
  "cited_rule_ids": ["R003"],
  "needs_human_review": true
}
```

Generation uses temperature `0.0`, JSON-object response mode and bounded tokens. The authority map in
the payload states that the engine owns every decision field and the model only drafts language.

### 5.2 Deterministic verification

The candidate is rejected when it:

- has missing or extra keys;
- returns empty explanation or recommendation text;
- cites a path that was not supplied;
- cites another rule;
- changes the engine's human-review flag;
- asserts approval, denial, payment or a clinical judgement;
- proposes automatic or unreviewed action;
- contains instruction-like content, including tested Base64-transformed forms;
- times out, returns invalid JSON, fails transport, or is not configured.

The fallback carries deterministic explanation and correction text, the rejection reasons, a
`fallback` decision and a new receipt. Missing model configuration in explicit model mode is visible;
it is not silently treated as a normal deterministic run.

### 5.3 Receipts and persistence

The receipt hashes claim/rule/status identity, explanation, correction recommendation, citations,
provider, security decision, rejection reasons and fallback state. Migration
`0004_assistance_security_envelope.sql` adds:

- `correction_recommendation`;
- `cited_evidence_paths`;
- `security_decision`;
- `receipt_sha256`;
- constraints for known decisions and 64-character lowercase hashes.

Legacy rows remain honest: their decision is `unrecorded` and no receipt is invented.

## 6. Model benchmark and deployment decision

### 6.1 Preserved historical run

The 2026-09-25 Tesla T4 run evaluated Gemma 4 E4B Q4, Phi-4 Mini BF16/Q4 and Qwen3 4B BF16/Q4.
Gemma 4 BF16 exceeded the notebook's declared fit threshold and was skipped.

| Candidate | Relevant observation | Decision |
|---|---|---|
| Qwen3 4B BF16 | Highest raw aggregate score (`0.7000`) | Rejected: schema and prompt-injection failures |
| Gemma 4 E4B Q4 | Best measured exact-contract rate (`75%`) | Next experimental candidate, not deployable |
| Phi-4 Mini variants | Ran within the recorded T4 environment | Failed at least one hard gate |
| Qwen3 4B Q4 | Lowest memory among the named Qwen variants | Failed hard gates |

All 22 manual semantic-support labels remain unadjudicated. Therefore the historical run has no
winner. Its raw CSV/JSON/environment artifacts remain under
`docs/verification/slm-benchmark/2026-09-25/`.

### 6.2 Updated v2 notebook

`notebooks/slm_explanation_benchmark_colab.ipynb` now measures the same five-field contract used by
the application. The next Colab run should compare at least:

- Gemma 4 E4B BF16 when the accelerator fits it;
- Gemma 4 E4B Q4;
- Phi-4 Mini BF16 and Q4;
- Qwen3 4B BF16 and Q4;
- raw, prompt-constrained, schema-constrained, verifier-only and complete-envelope conditions.

Hard gates include contract validity, citation validity, status invariance, prompt-injection success,
semantic support, false fallback, reviewer usefulness, latency and VRAM. Quantization is acceptable
only when the quantized candidate clears every hard gate and is not materially worse than its
unquantized counterpart.

### 6.3 Fine-tuning decision

Fine-tuning is not the next step. The current corpus is too small and incompletely adjudicated to
justify changing weights. First establish a v2 baseline with constrained decoding and the complete
security envelope. Fine-tune only when repeated errors form a stable category, the training and
held-out sets are independently reviewed, and the tuned model still passes every safety gate.

## 7. JEV advisory layer

The JEV integration is deliberately independent from the prose-generating SLM. `JevJudge` submits a
typed state and typed questions to TypeSafe AI System One and stores typed answers in a sidecar.
`NullJudge` is the default and performs no network I/O. All provider failures are typed, redacted and
made inert.

The current questions assess grounding, status agreement and attention. They are advisory signals,
not decisions. A JEV answer cannot change a result record, approve SLM language or reorder the queue
until a separately recorded evaluation authorizes that use. Live access has not been tested because
no credential/model access was supplied.

## 8. Configuration and deployment

The intended local stack is:

```bash
Copy-Item .env.example .env
docker compose up -d --build
```

Services:

- PostgreSQL 16 at `localhost:5432`;
- FastAPI at `http://localhost:8000` and OpenAPI at `/docs`;
- Next.js at `http://localhost:3001`;
- the legacy fallback at `http://localhost:8000/review`.

Model assistance is selected with:

```text
CLAIMGUARD_EXPLAIN_MODE=model
CLAIMGUARD_EXPLAIN_BASE_URL=<OpenAI-compatible endpoint>
CLAIMGUARD_EXPLAIN_MODEL=<winner from secured v2 benchmark>
CLAIMGUARD_EXPLAIN_API_KEY=<optional endpoint secret>
```

Leaving endpoint/model blank produces an explicit safe fallback. No repository secret is required or
committed. JEV stays disabled unless `CLAIMGUARD_TYPESAFE_API_KEY` is set and `claimguard judge probe`
confirms the offered model.

## 9. Verification evidence at release

> **These are the release-day counts (2026-09-26).** Verification added on 2026-09-27
> (adversarial boundary cases and their CI tests) moved them: the clean worktree now
> reports **650 passed / 46 skipped**, the pack-present suite **696 passed**, and the
> frontend **17 passed**. Current status lives in
> `docs/verification/PHASE-1-GAP-ANALYSIS.md`.

Commands were run from the release worktree after the final formatting pass:

| Gate | Result |
|---|---|
| Clean-worktree backend | **610 passed, 39 skipped, 0 failed**; every skip explicitly names the absent mentor pack |
| Merged `main` backend | **649 passed, 0 skipped, 0 failed** with the local gitignored nested mentor pack present |
| `uv run --extra dev ruff check .` | Passed |
| `uv run --extra dev ruff format --check .` | 143 files already formatted |
| Focused strict Pyright | 0 errors, 1 existing private-test-helper warning |
| `npm test -- --run` | **11 passed in 3 files** |
| `npm run lint` | Passed |
| `npm run typecheck` | Passed |
| `npm run build` | Next.js production build passed; `/` and `/_not-found` prerendered |
| Notebook JSON parse | Passed |
| `git diff --check` | Passed; Windows line-ending notices only |
| Browser verification | Demo mode (`NEXT_PUBLIC_DEMO_MODE=true`) rendered; responsive three-column desktop grid confirmed; recommendation copied into the correct note. **Live mode was verified separately on 2026-09-26**: with the API origin set at build time, the cockpit loaded a real queue (13 claims / 29 findings), opened a claim, showed the evidence chips and the security panel, and recorded a decision (queue went 29 unresolved → 28 unresolved / 1 resolved, audit entry `reviewer-12 · Confirm Issue`) |

The public mentor data result remains 1.0000 status accuracy on all 9,000 public claim-rule labels,
but this is not evidence of real-claim accuracy or held-out performance.

## 10. Known limitations and explicit non-claims

1. No authentication, tenancy or role-based access control is implemented.
2. The displayed reviewer identity is configuration, not verified identity.
3. The audit ledger is tamper-evident, not deletion-proof or externally anchored.
4. No real PHI, payer integration, production denial rate or clinical outcome has been tested.
5. The mentor's private 200-claim held-out set has not been seen.
6. No v2 SLM checkpoint has passed the secured benchmark.
7. JEV has not made a live request and must remain advisory.
8. The model verifier checks structural and bounded semantic invariants; it is not a proof of factual
   relevance. Human review remains required.
9. The reviewer queue has no server-side pagination, saved views or full command palette.
10. Temporal remains a spike and is not part of the running request path.
11. No OCR capability is claimed or required by the current pack.
12. Docker Compose configuration was validated, but a complete production-like multi-container load
    and failure test remains future work.

> The tenancy / RBAC / observability items above (1–3, 10, 12) describe the state at release. The
> target plan for them is `§13` below; it is a guide, not a claim that they are already shipped.

## 11. Remaining work by priority and ownership

### P0 — project leads / senior implementation

1. Run the secured v2 notebook in Colab, complete two-reviewer semantic adjudication and select a
   deployable SLM only if every hard gate passes.
2. Configure the winning endpoint and run an end-to-end model-assisted staging evaluation.
3. Add authentication, tenant isolation, RBAC and server-derived actor identity before any real data.
4. Test migration `0004`, rollback/backup procedures and the complete Compose stack in a clean
   environment.
5. Run the mentor scorer and independent conformance gate immediately before submission.
6. Test against the private held-out set when mentors provide it; do not tune against it.
7. Record the demo video and produce the jury pitch deck from verified claims only.

### P1 — suitable beginner-team work with senior review

- B1: adjudicate SLM explanations/recommendations, label unsupported statements, expand adversarial
  cases and write reviewer-usability notes.
- B2: run the reproducible Colab matrix, capture latency/VRAM/quality artifacts and compare
  quantized versus unquantized candidates without choosing deployment policy.
- B3: build rulebook retrieval evaluation and evidence-relevance labels; keep it out of the status
  decision path.
- Frontend: pagination UX, saved filters, empty/error states, keyboard shortcuts and print styles.
- Documentation: screenshots, demo narration, operator FAQ and submission checklist.

### P2 — later production hardening

- external audit anchoring/WORM retention;
- observability dashboards and alert thresholds;
- load, soak, chaos and recovery testing;
- endpoint cost and capacity measurements;
- localization and accessibility review with real users;
- approved secret management and key rotation.

> The auth/tenancy P0 item and the observability P2 items above are expanded into the phased
> P0–P4 plan in `§13` (a target guide, not an as-built description).

## 12. Operational handoff checklist

Before changing the engine, read `docs/10-ADR-Starter-Pack-Authority.md`. Before changing the UI or
assistance layer, read `PRODUCT.md`, `DESIGN.md`, `docs/16`, `docs/18` and `docs/19`.

For every release:

1. keep the frozen 15-key record unchanged;
2. keep model/judge provenance in sidecars;
3. apply migrations in order through `0004`;
4. run backend, lint, format, types, frontend tests and production build;
5. run mentor conformance locally when the nested pack is present;
6. archive benchmark inputs, outputs, environment and manual labels together;
7. state failures and missing evidence explicitly;
8. never call a model deployable merely because it has the highest average score.

The detailed repository map and the commands are in `docs/11-Architecture-and-Data-Flow.md` and
`docs/13-Technical-Report.md`.

For operations / telemetry additions beyond this release checklist, follow the target guide in
`§13` (Technical Manager / Reviewer platform) and keep its claim-blind and additive-migration
constraints.

## 13. Technical Manager / Reviewer platform implementation guide

> **Status:** This section is a **target implementation guide** for the evolving clinic/tenant
> platform. It describes what should be built and how it should behave; it is **not** a claim that
> every item is already shipped. "Current" is only used where a state exists today; everything else
> is target. It preserves the product posture: **review, do not adjudicate**, synthetic-only data,
> and no claim content in operational surfaces.

### 13.1 Purpose and target outcome

- The Technical Manager / Technical Reviewer operates the platform **inside the product UI**.
- They see technical state, investigate claim-processing failures, and act on incidents **without
  opening Grafana / Prometheus / Loki / Tempo**.
- They are **claim-blind**: no claim content, patient/member data, raw findings, documents, or
  reviewer decisions.
- Observability and business traceability are **different sources**, shown together only when useful
  (e.g., a run/correlation timeline beside aggregate job status).

### 13.2 Tenant and role model

| Element | Target rule |
|---|---|
| Tenant | One clinic = one tenant (`tenant_id`). |
| Access | Global user accounts; access only through **active** `clinic_memberships(tenant_id, user_id, role)`. |
| Identity | Active tenant and user come from the **signed HttpOnly session**; the role is resolved **server-side on every request**. |
| Technical permissions | Technical Manager / Reviewer hold only `READ_OPERATIONS` and `MANAGE_OPERATIONS`; claim-content endpoints must return **403**. |
| Business roles | Clinic admin / reviewer / lead permissions remain separate and are **not expanded here**; the technical role never inherits them. |
| Tenant scope | **Never** accepted from a user-provided query parameter. Future RLS / equivalent isolation is a **production gate (P4)**. |

### 13.3 User experience / screens

| Screen | Purpose and content |
|---|---|
| Operations overview | API / database / schema / rules readiness, overall status, source freshness, active alerts. First thing a Technical Manager sees. |
| Intake Jobs | Tenant-scoped **aggregate** job counts / status / failures; **never source content**. |
| Model & Rule Versions | Active rule, model and provider versions in one place. |
| Metrics | Error rate, throughput, p95/p99 latency, CPU / memory / disk aggregates, database and queue health. |
| Logs | **Truly sanitized** runtime logs. Distinct from the existing intake-status / redacted-log page until that page is replaced or extended. |
| Traces / transaction investigation | Run / correlation timeline from submission through processing, rules, explanation, decision and audit — **without claim payload**. |
| Alerts / incidents | Severity, state, first/last seen, component, safe next action; acknowledge, assign, comment, resolve. |
| Audit integrity | Chain status and safe aggregate information only; no audit or claim contents for the claim-blind role. |
| Configuration | Only safe tenant-scoped operational toggles (e.g., intake enablement), every change audited. |

Shared UX conventions:

- **Overview-first, drill-down:** every screen opens with a summary and only expands into detail on
  interaction.
- **Freshness badges:** `healthy` / `degraded` / `stale` / `unknown` / `unavailable` / `loading` /
  `empty` / `permission denied` — explicit states, never silent blanks.
- **No clutter:** bounded cards, paginated tables, bounded time windows; no raw telemetry surfaces
  in the reviewer browser.

### 13.4 Technology stack and exact purpose

| Component | Exact purpose |
|---|---|
| PostgreSQL | Tenant-owned application data, operations state, audit ledger. **Never** used as a raw telemetry query surface. |
| Alembic | **Additive** schema migrations only. |
| FastAPI | Server-side operations API and the authorization boundary. |
| Pydantic | Response models and field allow-lists. |
| SQLAlchemy | Safe aggregate DB health queries and persistence. |
| Next.js / React | Technical Manager UI. |
| Next.js server proxy | Browser-to-platform path; **no telemetry credentials or URLs** reach the browser. |
| Signed HttpOnly session + backend membership resolution | Identity and tenant/role enforcement on every request. |
| OpenTelemetry Python SDK | Instrumentation for HTTP, DB, jobs and external calls; exporter optional. |
| OTLP / OTel Collector and existing `otel-lgtm` | Telemetry transport and local development backend. |
| Prometheus-compatible Mimir (or Prometheus) | Metrics storage and query. |
| Loki | Sanitized structured log storage and query. |
| Tempo | Distributed trace storage and query. |
| Grafana | Backend / operator source only — **not** the reviewer browser UI. |
| Alertmanager | Optional, later: external notification routing. In-platform alerts start in backend / Postgres. |
| structlog / python-json-logger | Allow-listed structured logs. |
| Tenacity | Bounded retries / circuit / failure handling where appropriate. |
| Docker Compose | Local reproducible telemetry stack. |
| pytest / ruff / pyright / CI | Proof and merge gates. |

### 13.5 End-to-end architecture and workflows

```text
Browser (Technical Manager UI)
   │  HttpOnly session — no telemetry credentials
   ▼
Next.js server proxy
   │  /v1/operations/* — server-side only
   ▼
FastAPI operations API  ── session → membership → role → permissions (403 for claim content)
   │
   ▼
operations adapters (health · metrics · logs · traces · jobs · integrations · audit)
   │
   ├──▶ PostgreSQL           application data, operations state, alerts, audit ledger
   ├──▶ Mimir / Prometheus   metrics
   ├──▶ Loki                 sanitized logs
   └──▶ Tempo                traces
          ▲
          │ OTLP (server-side export, optional)
   OTel Collector / otel-lgtm
```

Workflows:

1. **Normal health check.** Browser → proxy → operations API → health adapter → DB connectivity,
   schema version vs applied migrations, rules catalog load, intake state → overview cards with
   freshness badges. No claim content is involved.
2. **Source failure / stale data.** An intake job fails or a source goes stale → adapter marks the
   source `degraded` / `stale` → overview badge + alert row → Technical Manager sees a **safe next
   action** (e.g., restart intake; credentials are referenced, never displayed).
3. **Alert → investigation → audited action.** Alert created in backend / Postgres →
   acknowledged / assigned → Technical Manager inspects sanitized logs and the correlated
   run/correlation timeline (no payload) → acts (e.g., toggles intake) → action written to the
   append-only audit.
4. **Claim transaction investigation by safe reference.** A processing failure is reported with a
   run / correlation reference → Technical Manager pulls the timeline from the trace store plus
   aggregate job status — never the claim payload, which stays behind the claim-blind split.
5. **Configuration action and rollback verification.** Toggle intake → audit event → re-check
   overview health / staleness → roll back if needed, also audited.

### 13.6 Telemetry and audit data contracts

Allowed telemetry fields: service, route template, status class, duration, queue/job counts,
version, bounded error category, opaque correlation ID where needed.

Forbidden in telemetry: request/response bodies, raw URLs / query strings, claim / run / patient /
member / user identifiers **in metric labels**, emails, cookies, auth headers, filenames, SQL
parameters, free-text exceptions, prompts, clinical content.

Metrics label allow-list: `service`, `component`, `route_template`, `method`, `status_class`,
`queue_job_category`, `integration_category`.

- Correlation IDs may appear in logs and traces but **never** as metric labels.
- Telemetry keeps **short** retention; audit keeps **long / policy** retention. Separate storage and
  separate permissions.

### 13.7 Backend / API implementation

Target module boundaries (not yet existing):

- `claimguard/ops/` adapters for health, metrics, logs, traces, jobs, integrations and audit.
- Existing/current operations routes stay versioned under `/v1/operations/*` where applicable.
  Add **bounded endpoints** for metrics / logs / traces / alerts — never expose telemetry stores
  directly.
- Each adapter gets a timeout, circuit / freshness state, caching where safe, pagination, bounded
  time windows, redaction, and structured errors.
- Tenant / user / role are derived from the **backend session**; never from body or query.
- Alert state lives in backend / Postgres initially; Alertmanager is an optional later addition.
- Technical Manager actions are recorded in the **existing append-only audit path**. Only additive
  migrations — never a change to hash serialization or the frozen claim contracts.

### 13.8 Implementation phases and dependencies

| Phase | Depends on | Scope | Success condition |
|---|---|---|---|
| **P0 baseline / safety** | Agreed scope + reviewed clinic workspace | Synchronize reviewed clinic workspace; define data classification; verify 403 claim isolation; leak-canary tests | Technical role proves 403 on claim-content endpoints; canary string absent; gates green |
| **P1 instrumentation** | P0 | Optional OTel; initial allow-listed metrics / logs / traces; **collector outage cannot block claims** | Synthetic traffic produces safe metric/log/trace; claim flow unaffected when collector is down |
| **P2 platform presentation** | P1 | Operations overview, metrics, intake, versions, sanitized logs, traces, audit integrity screens | Technical Manager investigates without telemetry tools; every UI state is explicit |
| **P3 alerts / incident workflow** | P2 | Alerts in backend/Postgres; severity/state; acknowledge/assign/comment/resolve; runbooks | Alert → investigation → audited action works end-to-end; no claim data in alerts |
| **P4 production hardening** | P3 | RLS / equivalent isolation; secure Grafana; secret rotation; retention / residency; backup / recovery; SLOs; synthetic checks | All production gates pass including UAE / data-residency legal review |

### 13.9 Alerts and runbooks

Candidate alert conditions: health degraded, API / web unavailable, elevated 5xx / latency,
database unavailable, migration mismatch, intake-reject abnormality, explanation-fallback surge,
audit-integrity false.

- **No claim data in alerts** — alert fields are component, severity, state, first/last seen,
  category and safe next action.
- **Baseline before thresholds:** collect days of allow-listed synthetic/operational data before
  tuning any threshold.
- **Runbook fields:** title, component, severity, symptoms, safe next actions, escalation path,
  rollback steps, verification steps, owner.
- **Safe intake toggle semantics:** disabling intake stops new ingestion (a safety action); it never
  mutates or derives claims, and every state change is audited.

### 13.10 Security / privacy and non-overlap rules

- Synthetic-only data, always; no claim leakage into operational surfaces.
- The technical role remains **claim-blind**.
- No direct browser access to telemetry datasources, no Grafana iframe, no admin session.
- **Never change** the 17-key claim envelope, the 15-key rule result, the deterministic engine, the
  audit hash serialization, the decision state machine, or the tenant/role model without owner
  agreement.
- **Additive migrations only.**
- UAE / data-residency and production-telemetry legal review is a hard gate before production (P4).

### 13.11 Verification / definition of done

Concrete checks that must pass before this guide is considered implemented:

- Actual synthetic traffic produces **safe** metrics, logs and traces.
- A technical user gets operations access **and 403** for claim content.
- A canary patient string is **absent** from telemetry.
- Collector / tool outage does **not** stop claims (fail-open telemetry, fail-closed safety).
- A tenant **cannot cross-read** another tenant's operations data.
- Alerts and configuration changes are **audited**.
- The UI has explicit `stale` / `unavailable` / `permission denied` states.
- Tests, lint, typecheck, migrations and Compose / runbook evidence all pass the release gates.

### 13.12 Final worklist

Practical order, with dependencies. **Start with P0** — do not try to build the whole observability
surface at once.

1. **Baseline agreement** — scope, synthetic-only commitment, claim-blind split, data
   classification. (feeds P0)
2. **P0 baseline / safety** — reviewed clinic workspace; `clinic_memberships` + role resolution;
   403 claim-isolation tests; leak-canary tests. (feeds P1)
3. **P1 instrumentation** — optional OTel; allow-listed metrics / logs / traces; collector-outage
   isolation tests. (feeds P2)
4. **P2 platform presentation** — operations overview and drill-down screens: metrics, intake,
   versions, sanitized logs, traces, audit integrity. (feeds P3)
5. **P3 alerts / incidents** — backend/Postgres alerts, runbooks, acknowledge/assign/comment/resolve,
   audited actions. (feeds P4)
6. **P4 production hardening** — RLS / equivalent isolation, secure Grafana, secret rotation,
   retention / residency, backup / recovery, SLOs, synthetic checks, legal review.

This guide is deliberately comprehensive so every future change has a target; implementation should
proceed phase by phase, starting with P0.
