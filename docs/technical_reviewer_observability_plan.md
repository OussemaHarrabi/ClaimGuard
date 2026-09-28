# Technical Reviewer Observability — Recommendation

**Status:** proposed product direction, not a final implementation. This document sets the goal and the implementation approach for one in-platform observability workspace. It does not record what already exists, who owns what, or current branch state.

**Posture:** review, not adjudicate. The workspace reports the technical state of the platform and supports investigation. It never approves, denies, or advises on a claim.

## 1. Goal and the questions the workspace must answer

**Goal.** The Technical Reviewer opens the ClaimGuard platform and can understand the important technical state of the whole platform, investigate claim-processing problems, and act on incidents — without opening Grafana, Prometheus, Loki, Tempo, or any other external tool interface. External observability tools are backend engines; the browser talks only to our platform backend.

The workspace must answer these questions with evidence:

| Question | What answers it |
|---|---|
| Is the platform healthy? | Overview verdict and per-source freshness status |
| What is failing? | Service health, resource, and queue panels |
| Who/what is affected? | API error/latency, queue backlog, integration status, linked transactions |
| Is a claim transaction progressing? | Transaction view: submission → processing → rules → explanation → decision/audit |
| When did it start? | Alert first-seen, log timeline, trace start time, audit timestamps |
| What changed? | Release, schema, rules, and model version markers |
| What should I do next? | Alert detail with severity, state, affected component, and next action |
| Is the data fresh and trustworthy? | Source last-seen stamps, audit integrity status, never stale-shown-as-healthy |

## 2. Core rule

One platform workspace, one backend boundary:

- The frontend calls only our platform backend. It never holds a datasource URL or credential and never resolves a telemetry tool address.
- Backend adapters query the observability engines (metrics, logs, traces) and the business audit store on behalf of the UI.
- Audit data (business traceability) and telemetry (system observability) remain separate sources with different integrity, retention, and permissions. The UI shows them together when useful — for example a transaction page joins audit events and a trace on a shared correlation id.

## 3. What the Technical Reviewer should see

| Area | What appears in the UI | Why it matters |
|---|---|---|
| Overview/status | One-page verdict, per-source freshness grid, active alerts, version markers | Answers "is the platform healthy and fresh?" in one glance |
| Services and dependencies (API, workers, database, queues, external integrations) | Per-component cards: readiness, resources, error rate, latency, backlog, integration reachability | Locates the failing component and its blast radius |
| Claim transaction investigation (submission → processing → rules → explanation → decision/audit) | Timeline of phases, span waterfall, versions used, linked audit events per run | Answers "is a claim transaction progressing?" for a specific run |
| Metrics (error rate, throughput, p95/p99 latency, CPU/memory/disk aggregates, queue backlog) | Time-series panels per endpoint class and service | First degradation signal; capacity and saturation visibility |
| Logs (searchable redacted logs with time, service, severity, correlation id) | Log viewer with filters and redaction badges | Cross-service debugging on a shared correlation id |
| Traces (trace timeline/span durations and errors) | Trace search, span list and detail with duration and status | Distributed-view drill-down for one run |
| Alerts/incidents (severity, state, first/last seen, affected component, next action) | Alert list and detail with runbook/next action and action buttons | Actionable operations inside the product |
| Business traceability/audit (who did what, when, claim/run reference, decision/access/config events, integrity status) | Bounded audit search, event list, chain-integrity banner | Trust in the record; every incident action appended to it |
| Release/configuration markers (app version, schema/rules/model versions) | Version strip on every page | Answers "which release is running?" |

## 4. UX design

- **Overview first, drill-down on demand.** The overview is the landing page: verdict, freshness, alerts, versions. Every other destination is a drill-down from it.
- **Clear status states** that every panel can render, and never faked:
  - `healthy` — source answered within threshold
  - `degraded` — source answered but a condition is failing
  - `stale` — last answer older than the freshness threshold (never shown as healthy)
  - `unknown` — never queried in this window
  - `unavailable` — adapter errored (timeout/circuit open), distinct from stale
  - `loading` — in-flight, with skeleton
  - `empty` — no data in the window, with a hint to widen it
  - `permission denied` — backend answered 403; UI explains the missing role
- **Freshness and data-source badges** on every panel so a stale or unavailable source is visible, not silently ignored.
- **Incident-to-transaction links** so the reviewer can move from an alert to the affected runs, their traces, and their audit events.
- **No dashboard clutter.** Bounded, purpose-built views instead of a wall of generic panels.

**Main screens:**

- **Overview** — verdict banner, source freshness grid, active alerts, version markers, recent transactions.
- **Services** — per-service cards with drill-down into one service's metrics.
- **Transaction** — search by run id or correlation id; phase timeline, span waterfall, versions, audit events.
- **Logs / Traces** — searchable log viewer and trace timeline for a correlation id.
- **Alerts** — active/resolved incidents with detail and action buttons.
- **Audit** — bounded, read-only search of business events with integrity status.

## 5. Backend implementation flow

```
Browser ──► ClaimGuard API ──► adapters ──► Mimir (metrics)
   │            │                  └──────► Loki (logs)
   │            │                  └──────► Tempo (traces)
   │            │                  └──────► Postgres (audit)
   └────────────┘
   (only platform API; no tool URLs/credentials)
```

1. **Instrument the app with OpenTelemetry** for HTTP requests, database calls, background jobs, and external calls, with low-cardinality attributes and structured redacted logs.
2. **Collect and store** metrics in a Prometheus-compatible backend (Mimir or Prometheus), logs in Loki, traces in Tempo. Grafana exists only as an internal source for our backend, never as a reviewer UI.
3. **Backend adapters** query these stores with timeouts, circuit breakers, query limits, pagination, caching, and freshness metadata (`last_success`, `last_error`, `last_data_at`) that drives the UI states.
4. **Backend exposes bounded platform APIs**:
   - `/v1/technical-reviewer/overview`
   - `/v1/technical-reviewer/health`
   - `/v1/technical-reviewer/metrics`
   - `/v1/technical-reviewer/logs`
   - `/v1/technical-reviewer/traces`
   - `/v1/technical-reviewer/transactions`
   - `/v1/technical-reviewer/alerts`
   - `/v1/technical-reviewer/audit`
5. **Frontend renders API responses** only, and never contains datasource credentials or URLs.
6. **Alert state initially managed in our backend** (definitions + evaluation loop + state rows). Add Alertmanager later only if external notification routing (email/webhook) is required.
7. **Technical Reviewer actions** — acknowledge, assign, comment, resolve — are stored as business audit events so every action is attributable and chain-protected.

## 6. What each tool does

| Tool | Role in this plan |
|---|---|
| OpenTelemetry | Instrumentation standard: spans for HTTP/DB/jobs/external calls, structured logs, metrics export |
| Prometheus / Mimir | Time-series storage for metrics; Mimir preferred for scale; queried by backend adapters only |
| Loki | Log storage and query; stores redacted structured logs |
| Tempo | Trace storage and query; stores spans correlated by trace id |
| Grafana | Internal source only: dashboards and bounded links generated backend-side; never a browser surface for the reviewer |
| Alertmanager (optional) | External alert routing (email/webhook) if needed later; not required for in-platform alerts |
| Postgres audit | Append-only, hash-chained business traceability; the authoritative record of claim runs and reviewer actions |

## 7. Privacy and safety rules

- **No PII/PHI or claim payloads in telemetry.** No patient identifiers, clinical content, or visible claim ids in metrics, logs, traces, or alerts.
- **Allow-list fields.** Only explicit, pre-approved fields are emitted and served; redaction is an allow-list, not a regex over free text.
- **No high-cardinality claim/user labels** on metrics. `claim_id`, `run_id`, and user ids never become metric labels.
- **Correlation ids are allowed** in logs and traces (opaque run/correlation id), but not as metric labels.
- **Backend access control.** All workspace routes mount behind the platform's access layer; enforcement is server-side, and the backend answers `permission denied` when a role is missing.
- **Bounded queries.** Time windows, pagination, and limits on every endpoint; no arbitrary query language reaches the reviewer.
- **Separate retention.** Telemetry is a short, configurable window; audit is long-lived per policy. Never stored together, never expired together.
- **Tenant-ready, not tenant-implemented.** A `tenant_id` can be carried in contracts in the future, but tenant design is out of scope for this document.
- **UAE/data residency legal review** before any production telemetry: confirm storage location, retention, and cross-region implications.

## 8. Implementation phases

- **Phase 1 — Workspace shell.** Overview page, health/source freshness, safe empty states (stale/unknown/unavailable/loading/empty). Read-only.
- **Phase 2 — Instrumentation.** OpenTelemetry instrumentation, metrics/logs/traces pipelines, structured redacted logs, transaction investigation joining audit events and traces.
- **Phase 3 — Alerts and incidents.** In-platform alert evaluation and incident workflow (ack/assign/comment/resolve), each action appended to the audit chain.
- **Phase 4 — Deeper integrations.** Tenant filtering, SLOs, deeper integration health, optional external routing (Alertmanager) if required.

## 9. MVP vs later

**MVP (must have):**

- Overview with verdict and source freshness
- Service/dependency health and version markers
- Metrics panels (error rate, throughput, p95/p99, resources, queue backlog)
- Redacted, searchable logs and traces with correlation ids
- Claim transaction investigation (submission → processing → rules → explanation → decision/audit)
- Alerts with severity, state, first/last seen, affected component, next action
- Audit view with integrity status
- Incident actions (ack/assign/comment/resolve) stored in the audit chain

**Later (should have):**

- SLOs and error budgets
- External notification routing (Alertmanager)
- Synthetic end-to-end checks
- Tenant filtering (after a tenant model exists)
- Anomaly detection and alert deduplication

**Explicitly out of scope:**

- Direct browser access to Grafana, Prometheus, Loki, Tempo, or Alertmanager
- A custom Grafana replacement or arbitrary query language
- Full request/response payload storage in telemetry
- Self-healing or automated remediation
- Continuous profiling / full APM
- A public status page
- Event sourcing or blockchain rewrite of the audit store

## 10. Acceptance checklist and recommendation

**Acceptance checklist:**

- [ ] A stopped or silent source renders as `stale` or `unavailable`, never as healthy
- [ ] Browser code and build contain no telemetry tool URL or credential
- [ ] No PII/PHI or claim payloads reach any workspace response (allow-list tested)
- [ ] No high-cardinality labels on metrics (tested)
- [ ] Audit events and traces join on one correlation value for a run
- [ ] Every incident action produces an append-only audit event
- [ ] With a telemetry source down, the workspace degrades gracefully and the claim review flow keeps working
- [ ] All workspace endpoints enforce bounded windows, pagination, and limits
- [ ] Access control is server-side; `permission denied` is rendered, not bypassed

**Recommendation.** Adopt the in-platform workspace as the product direction: one platform API boundary, backend-only access to observability engines, audit and telemetry kept separate but presented together, built read-only-first and phased. This keeps the reviewer inside the platform, preserves the review-not-adjudicate posture, and treats external observability tools as engines behind our own API.