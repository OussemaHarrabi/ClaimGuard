# ClaimGuard AI — Technical Reviewer Observability Implementation Recommendation

| Field | Value |
|---|---|
| Document type | **Proposed team decision**, not a final architecture |
| Decision status | **PROPOSED** — pending ADR and ownership sign-off |
| Relationship to docs | Concrete layer over `docs/obs_trace.tex`; `docs/05` remains the target blueprint |
| Posture | Review, not adjudicate. Synthetic-only data. |
| What this decides | Signals to show, tooling, backend flow, UX, phases, acceptance criteria, and the final worklist |
| Date | 28 September 2026 |
| Author | Proposed team decision |

## 1. Executive recommendation and decision boundary

**We recommend one in-platform Technical Reviewer workspace, backend-only integrations, read-only-first, delivered in additive phases.** The Technical Reviewer should never leave ClaimGuard to operate the platform; every observability and traceability capability is served through ClaimGuard's own API, and the browser never holds a credential for, or a URL of, any telemetry tool.

- **One workspace, not a dashboard pile.** A single review cockpit (extending the existing Next.js workspace) with an overview page and drill-downs, so "is the platform healthy and are the claim flows trustworthy?" is answered in one place. Grafana remains an operator back-end source that our backend consumes; it is not a second UI for the reviewer.
- **Backend-only integrations.** The platform queries Mimir (metrics), Loki (logs), Tempo (traces) and Postgres (audit) entirely from a new `claimguard/ops/` boundary. The frontend calls only `/v1/technical-reviewer/*` through the existing server-side proxy (`frontend/src/app/v1/[...path]/route.ts`), which already forwards `GET`/`POST`/`HEAD` to the API and forwards no credentials.
- **Read-only-first.** Phase 1 and Phase 2 add read-only surfaces (overview, health, metrics, logs, traces, transactions, audit). Writes arrive only in Phase 3, and only for the bounded incident workflow (ack/assign/comment/resolve), each write appended to the existing audit hash chain.
- **Additive phases.** Nothing already built is modified: the canonical model stays sealed, the rule engine is untouched, and the audit hash-chain contract (trigger + `claimguard/audit/chain.py` parity) is preserved. Every change is an additive migration or a new module.

**Decision boundary.** This document is a proposal for the team to ratify in an ADR before implementation. It does not change the product posture: the workspace reports status, health, and evidence; it never approves, denies, or advises on a claim. It also does *not* implement tenancy or authentication; those remain deferred, and this document only makes the contracts tenant-ready and auth-mountable.

**System observability and business traceability remain separate sources presented together.** System observability (metrics, logs, traces, alerts about how the *system* behaves) lives in the OTel stack; business traceability (the immutable, hash-chained record of what happened to which claim run) lives in `claimguard.audit_events` in Postgres. The two have different sources, integrity semantics, retention, and permissions, and they are never merged into one store. The workspace presents them side by side, joined on one correlation value (the run's 32-hex `trace_id`, see Sections 6 and 10).

## 2. Current repo baseline and gaps

All statements below were verified in the working tree on 2026-09-28. The intent is to be precise about what exists, what is provisioned but inert, and what is absent — no fabricated capability is claimed.

| Path | Verified state today | Relevance to this scope |
|---|---|---|
| `claimguard/review/app.py` | FastAPI surface: `GET /v1/health` returns `HealthResponse` (status, database, schema_revision, rules_ready, rules_dir, engine_rule_version); eight endpoints: `POST /v1/claims`, `GET /v1/runs/{run_id}`, `GET /v1/runs/{run_id}/claim`, `GET /v1/runs/{run_id}/results`, `GET`/`POST /v1/runs/{run_id}/decisions`, `GET /v1/queue`, `POST /v1/claims/{claim_id}/recheck`; explicit 503/404/409/422 bodies naming the fix | The seed for the operational overview; the pattern the ops surface extends |
| `claimguard/audit/chain.py` + `0001_initial_schema.sql` | Append-only, SHA-256 hash-chained `claimguard.audit_events`; SQL trigger `claimguard.audit_chain_insert()` is the canonical hash owner with a character-for-character Python replica; `claim_ref` is an opaque run id; `trace_id` is `NOT NULL`; `UPDATE`/`DELETE`/`TRUNCATE` revoked from `claimguard_app`; verifier function `claimguard.verify_audit_chain()` exists (migration comment mentions `GET /v1/audit/verify`, which is *not* registered in `review/app.py` today) | Business traceability exists and is authoritative; the audit view reads it and exposes chain verification; parity tests must stay green |
| `0002_review_workflow.sql` | `claimguard.rule_runs` (immutable; `trace_id` CHECK `'^[0-9a-f]{32}$'`), `rule_results` (15 frozen records), `review_decisions` (append-only) | The transaction/run record the ops *transactions* view joins against |
| `claimguard/review/audit_events.py` | Appends `validated` (run) and `review_decided` (decision) events with a transaction-scoped advisory lock and `clock_timestamp()`; the free-text `reason_code` carries a `key=value` provenance descriptor | The exact append mechanism Technical Reviewer incident actions will reuse |
| `claimguard/config.py` | `Settings` reads `CLAIMGUARD_*` env; `otel_endpoint` (default `http://localhost:4318`), `otel_service_name` (default `claimguard`), `temporal_enabled` (default `False`) | Endpoint configured; nothing exports to it yet |
| `pyproject.toml` | Declares `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-sqlalchemy`, `structlog`, `python-json-logger`, `tenacity` | Declared, **not initialized**: no import of `structlog` or the OTel SDK exists anywhere under `claimguard/` |
| `docker-compose.yml` | `otel-lgtm` service (`grafana/otel-lgtm:0.32.1`): Grafana UI on :3000, OTLP/HTTP receiver on :4318, volume `lgtm_data`; the file's own comment states "no code constructs one today, so nothing is exported yet"; Temporal is an opt-in profile; **no Alertmanager service** | Backend stores are provisioned; the collector has no scrape/host-metrics configuration and no alert routing today |
| `claimguard/workflow/claim_workflow.py` | Thin Temporal workflow (`ClaimValidationWorkflow`); activities are unbound placeholders (`NotImplementedError`); disabled by default | Future span source for the claim flow; not observable until the worker is bound |
| `claimguard/ingest/fhir.py` | FHIR intake populates `src` only for `claim_id` (`src["claim_id"] = f"{pointer_base}/id"`); every other provenance pointer is absent (known gap, do not rediscover) | Bounded until fixed: the transaction view cannot yet cite per-field source pointers for FHIR-intaken claims |
| `frontend/src/app/v1/[...path]/route.ts` | Server-side proxy: only `GET`/`POST`/`HEAD`, no cookies and no arbitrary headers forwarded, `cache-control: no-store`, 502 naming the origin | The only path from browser to API; ops endpoints are all `GET` plus `POST` incident actions, so the existing proxy suffices |
| `frontend/src/components/review-cockpit.tsx`, `review-workspace-app.tsx` | The current reviewer workspace (queue, run detail, decisions) | No ops console, alerts, logs, traces, or audit views exist yet |

**Absent today (verified):** telemetry export (inert), structured JSON logging wiring, an ops boundary (`claimguard/ops/` does not exist), alerts/incidents, authentication/RBAC/tenancy, per-tenant filtering, SLOs, deployment/version markers beyond `/v1/health`, external integration health, and any API exposing audit chain verification.

**Known drift that blocks clean alert semantics (do not rediscover):** `claimguard/contracts.py` defines `Severity` = {`info`, `warning`, `high`, `critical`} and `Tone` containing `neutral`; migration 0001's `findings` CHECK allows severity {`info`, `minor`, `major`, `critical`} and tone {`red`, `amber`}; migration 0002's `rule_results` uses yet another set {`high`, `medium`, `low`}. Three severity vocabularies exist. Alert severity mapping and any rule-health aggregation must not be built on these enums until the drift is reconciled (worklist item 2).

## 3. Product goal, persona, and the questions the workspace must answer

**Persona.** The *Technical Reviewer* is the operator who keeps ClaimGuard running and trustworthy: they answer support questions about a specific claim run, they notice when the platform is degrading, and they are accountable for acting on alerts. They are not the clinical reviewer (who uses the existing queue/decision surface) and not a Grafana operator.

**Product goal.** One workspace that answers eight operational questions with evidence, each answered by a specific signal:

| Operational question | Signal that answers it |
|---|---|
| Is the platform healthy? | Overview verdict + source-freshness grid (Section 4, MUST-1) |
| What is degraded? | Per-service health/readiness and resource panels (MUST-2, MUST-4) |
| Who/what is affected? | API error/latency panels, queue/job health, external integration health (MUST-3, MUST-5, SHOULD-13) |
| When did it start? | Alert first-seen, log timeline, trace start time, audit `at` timestamps (MUST-8, MUST-9, MUST-11) |
| Which release? | Version markers: app version, `schema_revision`, `engine_rule_version`, per-run `rule_version` / `model_version` / `prompt_version` (MUST-10) |
| Which claim transaction/run? | Transaction view joined on `run_id` / `trace_id` across `rule_runs`, `audit_events` and Tempo (MUST-7) |
| What action is next? | Alert detail with runbook/next-action; incident ack/assign/comment/resolve (MUST-9, SHOULD-16) |
| Is the data fresh and trustworthy? | Source last-seen stamps (never stale shown as healthy), chain-verification status, latest run/audit timestamps (MUST-1, MUST-11) |

## 4. Recommended signal catalogue

The definitive catalogue. Priorities are MoSCoW. The frontend presentation is always via `/v1/technical-reviewer/*`; no cell in this table is a reason for the browser to touch a telemetry tool directly. "Backend API/adaptor" names the `claimguard/ops/` adapter family that serves the signal.

| Pri | Element | Source / tool | Backend API / adaptor | Frontend presentation | What it shows / why it matters | Privacy / cardinality boundary |
|---|---|---|---|---|---|---|
| MUST | Platform overview and data-source freshness | Aggregated adapters: Postgres + Mimir + Loki + Tempo + audit chain | `/v1/technical-reviewer/overview` | Landing page: verdict banner, per-source grid with last-seen | Shows one verdict per source with freshness timestamps; answers "healthy and fresh?" in one glance | Statuses only; no claim-level data |
| MUST | API/service health and readiness | `GET /v1/health` (exists: schema revision, rules catalogue, DB reachability) | `/v1/technical-reviewer/health` | Service cards, extend not replace `/v1/health` | Readiness of API, DB, rules catalogue; why: the existing endpoint already reports the two most common failure modes (unmigrated schema, missing rules dir) | No payload content |
| MUST | API error rate, throughput, p95/p99 latency | OTel FastAPI instrumentation, spans → Mimir | `/v1/technical-reviewer/metrics` | Line/heat panels per endpoint class | Error ratio, requests/sec, latency percentiles per endpoint; why: first degradation signal | Labels only: endpoint class, method, status class; no claim ids |
| MUST | Resource health (CPU, memory, disk) at aggregate service/container level | Container/host metrics via the LGTM collector (needs a scrape or host-metrics receiver; none configured today) | `/v1/technical-reviewer/metrics` | Per-service resource cards | Usage and saturation per service/container; why: catches runaway memory/disk before requests fail | Container-level aggregates only |
| MUST | Background jobs / Temporal / queue health | Temporal (opt-in profile, disabled by default) + in-process counters | `/v1/technical-reviewer/health` (+ `jobs` section) | Queue panel: backlog, failures, retries, oldest age | Stuck runs are silent losses; why: queue depth and failure counts are the earliest signal | Counts only; today the engine runs in-process, so this renders "unknown / not applicable" until Temporal is enabled |
| MUST | Database health (connectivity, pool pressure, query latency, slow-query counts) | SQLAlchemy instrumentation + DB statistics | `/v1/technical-reviewer/metrics` + `health` | DB card in Services | Connectivity, pool usage/waits, query latency percentiles, slow-query counts; why: Postgres holds runs and the audit ledger | Aggregate only; never query text, never claim content |
| MUST | Claim-processing transaction flow: submission → normalization → rule evaluation → explanation → decision/audit | OTel traces (Tempo) + `rule_runs` + `audit_events` | `/v1/technical-reviewer/transactions` + `traces` | Timeline + span waterfall per run | Per-phase duration, status, versions and audit events for one run; why: answers "which run, what happened, when" | Join on `run_id`/`trace_id`; no envelope content; FHIR provenance stub limits evidence citation until fixed |
| MUST | Centralized structured logs with correlation ID, severity, component, timestamp, redaction | Structured JSON logs → Loki (none shipped today) | `/v1/technical-reviewer/logs` | Log viewer with filters | Logs filterable by correlation id, component, severity, window; why: cross-service debugging | Allow-list redaction before serving; no prompt/response content |
| MUST | In-platform alerts with severity, state, first seen, last seen, affected component, runbook/next action | Backend alert state (Postgres), evaluated from bounded metric checks (Alertmanager gap, Section 6.2) | `/v1/technical-reviewer/alerts` | Alerts panel + detail with runbook | Active/resolved alerts with timeline and next action; why: actionable ops inside the product | Alert metadata only; severity vocabulary depends on enum reconciliation (Section 2) |
| MUST | Release/deployment/config/rule-version markers | App startup env, `schema_revision`, `engine_rule_version`, per-run versions | `overview` + `health` | Version strip on every page | App version, schema revision, rule catalogue version, model/prompt versions; why: "which release" question | No secrets in markers |
| MUST | Business audit/traceability view: claim lifecycle, decision, access, admin/config, Technical Reviewer actions; hash-chain status | `claimguard.audit_events` + `verify_audit_chain()` (Postgres) | `/v1/technical-reviewer/audit` | Audit trail search + chain-status banner | Events by kind with chain hashes and verification result; why: trust in the record; `kind` vocabulary already covers `validated`, `review_decided`, `escalated`, `llm_called` | `claim_ref` is opaque (run id); never visible claim ids; read-only |
| SHOULD | Per-tenant view (deferred, tenant-ready contracts) | Reserved `tenant_id` scope in contracts only | `/v1/technical-reviewer/*` accepts an unused tenant filter | Filter control disabled until tenancy exists | Nothing until a tenant model exists; why: avoid contract rework later | No tenant model; enforcement explicitly not implemented |
| SHOULD | External integration health: LLM/SLM, document storage, payer/government/health APIs when present | OTel HTTP-client instrumentation + probes | `/v1/technical-reviewer/integrations` | Integration cards | Reachability, latency, error rate per external endpoint; why: "who/what is affected" | Endpoint + status only; no payloads |
| SHOULD | Authentication failures and suspicious activity once auth exists | Auth-service audit events (auth does not exist yet) | `audit` filter by kind | Security panel | Failed logins, denied access, role changes; why: security posture | No credentials ever; only after auth lands |
| SHOULD | Basic SLOs: availability, latency, processing freshness | Computed from Mimir aggregates + DB freshness | `overview` (SLO strip) | SLO panel with error budget | Objective health with thresholds; why: shared definition of "good" | Aggregates only |
| SHOULD | Incident workflow: ack/assign/comment/resolve with audit events | Backend incident state (Postgres) + `audit_events` | `alerts` `POST` actions | Incident detail with action buttons | Ownership and state transitions; why: accountability | Every action appends to the hash chain (Section 6.5) |
| SHOULD | Incident-to-transaction linkage and bounded audit search | Incident ↔ `run_id`/`trace_id` links | `transactions` + `alerts` | Cross-linked detail pages | From incident to affected runs to audit events; why: blast-radius view | Bounded windows and pagination |
| COULD | Aggregate business-flow gauges: claims/hour, stuck-run counts | Counters derived from `rule_runs` | `metrics` / `overview` | Gauge row | Processing cadence; why: capacity visibility | No per-claim metric labels |
| COULD | Synthetic end-to-end checks | Synthetic probe runs against `POST /v1/claims` | `health` (synthetic section) | Probe status card | Verifies the real submission path; why: catches broken pipelines | Synthetic data only |
| COULD | AI/assistant latency, error, token, cost signals (no prompt/content) | LLM instrumentation (B1 territory) | `metrics` (AI section) | AI panel | Model latency/errors/tokens/cost; why: LLM performance and budget | No prompts, no content, no PII |
| COULD | Safe anomaly detection and alert deduplication | Bounded analysis over Mimir aggregates | `alerts` backend | Suppressed/duplicate badges | Less noise; why: alert fatigue is real | Aggregate-only analysis |
| COULD | Backend-mediated deep links or limited embedded panels, only if approved | Grafana signed/one-time links generated backend-side | `links` endpoint | "Open in Grafana" button (opt-in) | Advanced drill-down for the reviewer; why: escape hatch without browser credentials | Short-lived backend-generated links; default is no (open decision D8) |
| WON'T NOW | Direct browser access to Grafana/Prometheus/Loki/Tempo/Alertmanager | — | — | — | Never; the browser is never an authorized client of telemetry | No telemetry URLs or credentials in browser code |
| WON'T NOW | Custom Grafana replacement or broad arbitrary query language | — | — | — | We consume Grafana-family stores, we do not rebuild them | Bounded endpoints only |
| WON'T NOW | Per-claim/per-user metric labels | — | — | — | Cardinality and PII risk make this non-negotiable | Unbounded-label metrics forbidden |
| WON'T NOW | Full request/response payload storage | — | — | — | Privacy boundary; pointers and hashes only | Never returned by any ops endpoint |
| WON'T NOW | Continuous profiling / full APM, automated remediation, public status page, event-sourcing/blockchain rewrite | — | — | — | Out of scope by decision, not by convenience | — |

## 5. UX information architecture

One workspace, eight destinations. The overview is the landing page; everything else is a drill-down. The hierarchy is *status first, detail on demand*: the user reads a verdict, then opens the affected component or run.

| Destination | Purpose | Key content |
|---|---|---|
| Overview | Land, triage, answer "is it healthy?" | Verdict banner; per-source freshness grid (Postgres, Mimir, Loki, Tempo, audit chain) with last-seen; active alerts; SLO strip; version markers; recent transactions |
| Services | Component health | Per-service cards: readiness, resources, error rate, p95/p99; drill into a metrics panel for one service |
| Transaction investigation | One run, end to end | Search by `run_id`, `claim_id`, or `trace_id`; timeline of phases and audit events; Tempo span waterfall; linked logs; rule/model/prompt versions; decision history |
| Logs | Debug and correlate | Query builder (time window, component, severity, correlation id); redaction badges on log lines; jump to trace/transaction from a log |
| Traces | Distributed-view drill-down | Trace search by id/attribute; span list and detail with duration and status |
| Alerts/incidents | Act on problems | Active/inactive lists; detail with severity, first/last seen, affected component, runbook; ack/assign/comment/resolve actions |
| Audit/traceability | Trust the record | Bounded search by kind, `claim_ref`, `trace_id`, time; chain-verification banner; read-only |
| Integrations/config | External adapters and markers | Adapter health (LLM/SLM, storage, future payer/health APIs); release/rule-version markers; retention configuration view |

**States every panel can render.** No panel is allowed to fake health:

- **healthy** — source answered within freshness threshold.
- **degraded** — source answered but a health condition is failing.
- **stale** — last answer is older than the freshness threshold; shown as stale, never as healthy (AC1).
- **unknown** — the source has never been queried in this window.
- **source unavailable** — the adapter errored (timeout/circuit open); distinct from stale because it distinguishes "quiet" from "down".
- **loading** — in-flight, with skeleton, not a blank screen.
- **empty** — no data in the window; with a hint to widen it.
- **permission denied** — reserved for the future auth layer; the backend answers 403 and the UI explains the missing role.

**Frontend rule.** The frontend calls only `/v1/technical-reviewer/*` (and existing review endpoints) on its own origin through the existing server-side proxy; it never embeds a datasource credential, never resolves a telemetry URL, and renders whatever state the backend reports, including source failures.

## 6. Concrete backend implementation flow

### 6.1 Instrumentation

- **OpenTelemetry SDK initialization** in `claimguard/ops/` (or app startup, owned by SeniorDev): configure `TracerProvider`, `MeterProvider`, and the OTLP/HTTP exporter to `CLAIMGUARD_OTEL_ENDPOINT` (already in `config.py`, default `http://localhost:4318`; the compose override `CLAIMGUARD_OTEL_ENDPOINT=http://otel-lgtm:4318` must be added in Phase 2). All deps are already declared in `pyproject.toml`.
- **FastAPI and SQLAlchemy instrumentation** via the declared `opentelemetry-instrumentation-fastapi` and `opentelemetry-instrumentation-sqlalchemy` packages: one span per request and one per SQL execution, with low-cardinality attributes only.
- **HTTP-client instrumentation** for external calls (LLM provider, future integrations) with endpoint + status-class attributes, never bodies.
- **Background-workflow boundaries.** The claim flow is currently in-process inside `review/app.py` (submit → evaluate → explain → record). Phase 2 instruments those stages as child spans under the request span and attaches the run's existing 32-hex `trace_id` (Section 10, D6). When the Temporal worker is bound (`claimguard/workflow/claim_workflow.py`), workflow/activity spans join the same trace via `ClaimInput.trace_id`.
- **Structured JSON logs with an allow-list.** Wire `structlog` and `python-json-logger` (declared, unused today) into the API process. Emit a fixed field set:

```text
ts, level, logger, component, correlation_id (run/trace id), request_id,
method, path (bounded), status_code, duration_ms, error_type, message
```

  Everything else is dropped. Redaction is an allow-list, not a regex over free text (Section 8).

- **Metrics with low-cardinality labels.** `claimguard_*` metric names; allowed label sets:

```text
{service, component, endpoint_class, http_method, http_status_class,
 queue, job, integration}
```

  Unbounded values (`claim_id`, `run_id`, user ids) are forbidden.

### 6.2 Collection and storage

- **OTLP → `otel-lgtm`.** The app exports OTLP/HTTP to the already-provisioned single container (Grafana + Loki + Mimir + Tempo, `docker-compose.yml`). No new service is required for metrics, logs, or traces; the compose change is limited to setting the endpoint and, in Phase 2, adding a host-metrics/scrape receiver so *resource* metrics (MUST-4) have a source — none is configured today.
- **Mimir** stores Prometheus-compatible metrics; **Loki** stores structured logs; **Tempo** stores traces. **Grafana** is an *operator/back-end source only*: our backend may query it for dashboards or use it to generate bounded deep links (COULD), but it is never a browser surface for the reviewer.
- **Alerts: Alertmanager or a bounded backend alert state.** *Recommendation:* start with a bounded backend alert state in Postgres (alert definitions + evaluation loop in `claimguard/ops/alerting.py`, state rows written by the ops service from bounded metric checks). This is tenant-ready, auditable, and does not depend on a tool absent from the stack. *Current-compose gap:* `otel-lgtm` does not include Alertmanager and no Alertmanager service is defined. Add Alertmanager to compose only if external routing (email/webhook fan-out) is required — open decision D7.

### 6.3 Adapters and repositories in `claimguard/ops/`

New boundary, SeniorDev-owned, additive:

- `ops/adapters/` — one adapter per source: `db.py` (health, pool, query stats via SQLAlchemy), `mimir.py` (bounded PromQL over metrics), `loki.py` (bounded LogQL over logs), `tempo.py` (trace search/detail), `audit.py` (audit reads + `verify_audit_chain()`), `temporal.py` (queue stats, only when enabled), `integrations.py` (external probes).
- **Backend-only credentials.** Telemetry credentials live in `CLAIMGUARD_*` env consumed by `claimguard/config.py`; never in the browser, never in frontend build args.
- **Timeout, circuit breaker, cache, freshness.** Each adapter has a default timeout (order of 1–2 s), a tenacity circuit breaker (dependency already declared), a short in-process cache, and per-source metadata `last_success`/`last_error`/`last_data_at` that drives the stale/unknown states (Section 5).
- **Bounded query windows and pagination.** Default window 15 min, maximum 24 h; explicit pagination; query limits; server-side redaction before any data leaves the backend.

### 6.4 API endpoints under `/v1/technical-reviewer/...`

Names only — contracts are Phase 0 output and deliberately not over-specified here. All are `GET` except the incident actions:

- `/v1/technical-reviewer/overview` — aggregate verdict, source freshness, active alerts, SLO strip, version markers.
- `/v1/technical-reviewer/health` — component readiness (extends the existing `/v1/health` shape).
- `/v1/technical-reviewer/metrics` — bounded time-series query.
- `/v1/technical-reviewer/logs` — redacted, searchable, correlated.
- `/v1/technical-reviewer/traces` — trace search and span detail.
- `/v1/technical-reviewer/transactions` — run/transaction index joining `rule_runs`, audit events, and traces.
- `/v1/technical-reviewer/alerts` — current alerts and incidents; `POST` sub-resources for ack/assign/comment/resolve.
- `/v1/technical-reviewer/audit` — audit search and chain verification (also covers the verification function that migration 0001 describes but `review/app.py` does not yet expose).
- `/v1/technical-reviewer/integrations` — external adapter health.

Response concerns on every endpoint: explicit pagination, bounded windows, server-side redaction, freshness metadata, structured errors in the existing `{detail, error}` shape, and never a raw payload, SQL, or prompt.

### 6.5 Audit writes for Technical Reviewer actions

Incident actions (ack/assign/comment/resolve) are business actions and must be audited. They reuse the existing append mechanism (`claimguard/review/audit_events.py`): advisory lock + `clock_timestamp()`, one event per transaction, appended to `claimguard.audit_events`. The 0001 `kind` CHECK list must be extended with incident kinds (e.g. `incident_ack`, `incident_assign`, `incident_comment`, `incident_resolve`); this is an *additive migration* owned by SeniorDev and does *not* touch the hash chain — `kind` is not part of the trigger's hashed field list:

```text
(prev_hash, at, claim_ref, trace_id, decision, reason_code, finding_ids, model_version)
```

so `claimguard/audit/chain.py` parity is unaffected. An incident state table (and its action log) is likewise a new additive table, not a change to existing ones.

## 7. End-to-end workflows

**W1 — Normal platform check.** Systems queried: `/v1/technical-reviewer/overview` (which fans out to adapters: Postgres health, Mimir/Loki/Tempo availability, audit chain status). The user sees the verdict banner green, the source grid with recent last-seen stamps, zero active alerts, SLO bars in budget, and the version strip. No drill-down needed; freshness timestamps are visible without a click.

**W2 — Incident detection and in-platform alert investigation.** The alert backend (bounded metric checks over Mimir) writes an alert row; the overview shows it. Systems queried: `alerts`, then `transactions` (incident → affected runs), `logs` (correlation id), `traces` (same correlation id), `audit` (who touched what). The user sees severity, state, first/last seen, affected component, runbook/next action, and a timeline; they ack, assign, comment, and resolve, each action appending an audit event (W4 mechanics).

**W3 — Claim transaction investigation from run id / correlation id.** Systems queried: `transactions` joins `claimguard.rule_runs` (identity, versions, `trace_id`), `claimguard.audit_events` (`validated`, `review_decided`, `escalated` events for that `claim_ref`), and Tempo (spans whose correlation id matches). The user sees a timeline: submission → normalization → rule evaluation → explanation → decision/audit, with phase durations, the 15-record summary, and the audit stamps (event id, chain hash). Where the FHIR provenance stub is unfixed, the UI notes that per-field source pointers are unavailable for that run rather than fabricating them.

**W4 — Audit review and action.** Systems queried: `/v1/technical-reviewer/audit`, which runs bounded searches over `audit_events` and reports `verify_audit_chain()` status. The user sees the event list (kind, opaque `claim_ref`, timestamps, decision, reason code, versions) and a chain banner ("intact" or broken-link details). The only writes available are incident actions, which append new events through the audited path — there is no edit/delete surface.

**W5 — Telemetry source failure / stale state.** Systems queried: any adapter; the failure is caught by timeout/circuit breaker. The user sees the source grid mark Mimir (or Loki, or Tempo) as *source unavailable* or *stale since <time>*; affected panels render the corresponding state and a retry affordance. Crucially, the review flow (`/v1/claims`, queue, decisions) is untouched: telemetry fails open (read-only convenience), while safety checks that cannot complete fail closed (existing invariant; e.g. ENV-001 semantics). No panel ever substitutes a guessed value for a missing source.

## 8. Privacy, security, and multi-tenancy guardrails

- **Synthetic-only, always.** The workspace, its fixtures, its demos and its screenshots carry only synthetic data — the repo invariant applies to observability exactly as to the product.
- **No PII/PHI in metrics, logs, traces, or alerts.** No patient identifier, clinical content, or visible claim id in any telemetry signal; enforcement is by construction (allow-list fields, bounded labels) plus review (AC6).
- **Allow-list, not regex-only, redaction.** Logs and traces served by the backend pass an explicit sensitive-field allow-list before leaving `claimguard/ops/`. Regex scrubbing may supplement but never replace the allow-list.
- **Pseudonymized correlation.** Telemetry and audit correlate on the opaque `run_id` (the existing `claim_ref` convention) and the 32-hex `trace_id`; the visible `claim_id` stays out of logs, traces, and alert metadata.
- **No high cardinality.** Unbounded label values are rejected at the metrics boundary; `claim_id`/`run_id`/user ids never become labels.
- **Backend auth and future tenant filter.** All `/v1/technical-reviewer/*` routes are defined to mount behind the future auth layer; contracts reserve an optional tenant scope field that is ignored until a tenant model exists. **Tenant enforcement is not implemented and this document does not claim it is.**
- **UAE residency/legal review as a gate.** Before any production telemetry retention, legal review confirms storage location, retention, and cross-region implications (D9); nothing ships to production telemetry ahead of it.
- **Separate retention.** Audit events are long-lived per policy (the immutable business record); telemetry is a short, configurable window. The two are never stored in the same place or expired together.
- **Never return raw payloads, SQL, or prompts.** No ops endpoint returns an envelope, a query string, an evidence value beyond the existing review surface, or an LLM prompt/response.

## 9. Non-overlap, team coordination, and phased roadmap

**Ownership.** SeniorDev owns the API surface, auth, audit, migrations, CI, and runtime configuration; HeadOfProject reviews the ADR and the scope; B1/B2/B3 instrument only their own components (the LLM service for AI signals, the eval harness for benchmark runs, intake/OCR for ingestion metrics); the web stream (B1/B3) builds the ops UI against the `/v1/technical-reviewer` contract. This work must not edit the canonical model or the rule engine, and must not change the audit hash serialisation.

| Phase | Scope | Coordination |
|---|---|---|
| 0 | Contracts and ADR: scope, ownership, endpoint contracts, correlation-id naming, sensitive-field allow-list, alert severity mapping | HeadOfProject (ADR/scope); SeniorDev (API, audit, CI) |
| 1 | Read-only overview + health + source status; no telemetry writes; stale/unknown states | SeniorDev (`claimguard/ops/` scaffold, extend `/v1/health`); Web (overview page) |
| 2 | OTel metrics/logs/traces; transaction investigation; structured JSON logs; compose endpoint + receiver config | SeniorDev (runtime config, CI, secrets); B1/B2/B3 only for their components |
| 3 | Alerts + incident workflow (ack/assign/comment/resolve) with audit events; additive migration for `kind` values and incident state | SeniorDev (audit, migrations); Web (incident UI) |
| 4 | Tenant enforcement (RBAC filters) and deeper integration health; SLOs | SeniorDev (auth, RBAC); only after a tenant model exists |

## 10. Acceptance criteria, risks, and open decisions

**Acceptance criteria.**

1. **AC1 — Freshness truthfulness.** The overview renders real source freshness; a stopped or silent source is shown as `stale` / `source unavailable`, never as healthy. Automated test: adapter failure produces the correct state on every affected panel.
2. **AC2 — No direct telemetry URLs in the browser.** Browser code (and the frontend build) contains no reference to Grafana, Prometheus, Loki, Tempo, or Alertmanager endpoints, and no telemetry credential. Enforced in review and by a CI grep.
3. **AC3 — Redaction tests.** Logs, traces, and alerts served by `/v1/technical-reviewer/*` pass the sensitive-field allow-list; a test feeds known PII-shaped values and asserts they never reach the response.
4. **AC4 — Low-cardinality tests.** A metrics test asserts no unbounded label values (no `claim_id`/`run_id`/user ids) are ever emitted.
5. **AC5 — Correlation across audit and traces.** A run's audit events and its trace resolve to the same correlation value (`run_id` / 32-hex `trace_id`) in the transaction view.
6. **AC6 — Alert actions audited.** Every incident ack/assign/comment/resolve produces an append-only audit event, and the parity test suite stays green.
7. **AC7 — Source outage safe degradation.** With Mimir, Loki, or Tempo down, the workspace renders stale/unavailable states and the review flow keeps working; no fabricated status.
8. **AC8 — Performance/query limits.** All ops endpoints enforce bounded windows, pagination, and query limits; a load test asserts p95 latency inside budget while the review flow is unaffected.
9. **AC9 — Role permissions.** Routes are auth-mountable and the permission matrix (audit vs telemetry vs incidents) is applied server-side once auth exists.
10. **AC10 — Tenant scope.** Contracts are tenant-ready; nothing claims tenant enforcement that is not implemented.

**Risks.** (R1) Enum drift (three severity vocabularies, Section 2) blocks alert semantics until reconciled. (R2) Telemetry volume/cost if unbounded labels or full payloads leak in — mitigated by AC3/AC4. (R3) Correlation fragmentation if the OTel trace id and the business `trace_id` diverge (open decision D6). (R4) Alert ownership ambiguity without a runbook/next-action contract (D5). (R5) Legal/retention exposure without the UAE residency gate (D9). (R6) Scope creep toward a Grafana replacement or arbitrary query language — the WON'T NOW list is explicit.

**Open decisions (recorded in the Phase 0 ADR).**

1. **D1 — Role permission matrix.** Who may see audit versus telemetry versus incidents.
2. **D2 — Alert ownership.** Which components may alert; who owns ack; re-alert behaviour.
3. **D3 — Retention/location.** Telemetry retention window per signal and storage location (local LGTM vs managed), after legal review.
4. **D4 — Tenant scope.** Tenant-ready metadata now; enforcement only with the tenant model.
5. **D5 — Runbook/next-action contract.** Where the "what action is next" content lives and who maintains it.
6. **D6 — OTel trace id vs existing business/audit `trace_id` naming.** `rule_runs.trace_id` is CHECK-constrained to 32 hex and `audit_events.trace_id` reuses it. Preferred: mint one 32-hex id per run, use it as the OTel trace id (W3C 128-bit is the same 32-hex shape) and as the audit `trace_id`, so Tempo spans and audit rows join on one value with no translation; the fallback is a `claimguard.trace_ref` span attribute. The ADR must pick one.
7. **D7 — Alertmanager in compose.** Backend alert state first; add `alertmanager` to compose only if external notification routing is required (current compose gap: none exists).
8. **D8 — Grafana deep links.** Bounded, backend-mediated, signed links only; default is no.
9. **D9 — Legal review.** UAE residency, retention, cross-region implications of logs and traces; a gate before production telemetry.

## 11. Final prioritized worklist

Numbered, with dependencies and ownership. Order is execution order within the phases; a later item waits on its dependencies only.

| # | Work item | Dependencies | Ownership |
|---|---|---|---|
| 1 | Phase 0 ADR + endpoint/contract review; record D1–D9 | — | HeadOfProject (review); SeniorDev |
| 2 | Reconcile Severity/Tone enum drift (`contracts.py`, 0001, 0002) into one vocabulary; update CHECKs via additive migration | 1 | SeniorDev (+ stream alignment) |
| 3 | Scaffold `claimguard/ops/`: adapters, settings, timeouts, circuit breaker, freshness metadata | 1 | SeniorDev |
| 4 | Overview + health + source-status adapters and endpoints (`/v1/technical-reviewer/overview`, `health`) | 2, 3 | SeniorDev |
| 5 | Frontend overview page + drill-down shell (states: stale/unknown/unavailable/loading/empty/denied) | 4 | Web (B1/B3) against contract |
| 6 | OTel initialization + structured JSON logging allow-list in the API process | 3 | SeniorDev |
| 7 | Metrics/logs/traces pipelines to `otel-lgtm` (compose endpoint + receiver config); transaction view | 5, 6 | SeniorDev; Web (view) |
| 8 | Alert evaluation backend + incident state (additive migration for `kind` values + incident tables); ack/assign/comment/resolve with audit | 7 | SeniorDev; Web (incident UI) |
| 9 | Alertmanager decision and optional compose addition | 8 | SeniorDev |
| 10 | Tenant-ready contracts + auth-mounting of ops routes | 8 | SeniorDev (after auth design exists) |
| 11 | SLOs + synthetic end-to-end checks | 7, 9 | SeniorDev; B2 (eval) |
| 12 | UAE residency/legal review gate on telemetry retention | before any production telemetry | SeniorDev + HeadOfProject |

**Bottom line.** Build the in-platform Technical Reviewer workspace read-only-first, over the existing audit chain and the provisioned LGTM stack, starting with Phase 0 (ADR and contracts) and Phase 1 (overview + health + source status). Telemetry export starts only in Phase 2, coordinated with SeniorDev, and no document in this series should claim it works before then.
