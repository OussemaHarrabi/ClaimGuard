# ClaimGuard — private technical-administration handoff

**For:** the senior teammate owning platform operations and observability  
**As of:** 28 September 2026  
**Classification:** private local document; synthetic demo credentials below. **Do not commit, paste into a PR, screenshot, or publish this file.** It is ignored by Git. Share it directly over a secure channel, then rotate the passwords when the demo environment changes hands.

## Read this first: the actual state

ClaimGuard is a **synthetic-data pilot**, not a clinical production system. The deterministic claim engine and reviewer workspace exist; the newer clinic tenancy and role workspaces are currently **uncommitted local work on `main`**, based on commit `a301c9c`. They are not available to someone who only clones the remote repository. Coordinate with the project owner before starting a feature branch so you both work from the same reviewed baseline. Do not copy these uncommitted files into a separate branch by hand.

The local PostgreSQL schema is at revision `0010`; `/v1/health` reported `status=ok`, `database=ready`, and `rules_ready=true` during the last verification. The local Next.js app was running on port 3001 and API on port 8000. The complete Python suite passed 726 tests and frontend Vitest passed 32 tests on 28 September. These are observations from the local machine, not a promise that a fresh clone has been deployed. Docker Compose end-to-end was **not** reverified on this machine in that pass.

Most importantly: `docker-compose.yml` already defines `otel-lgtm` (`grafana/otel-lgtm:0.32.1`) with Grafana on port 3000 and OTLP/HTTP on 4318. **The app does not construct an OpenTelemetry exporter today.** Starting Grafana will show an observability sandbox, not ClaimGuard telemetry. The technical workspace's “Redacted Logs” currently means intake-job status rows, **not** runtime exception or HTTP logs. The `CLAIMGUARD_OTEL_*` values in `.env.example` are declared settings but are not read by a telemetry pipeline. Do not present dashboards or tracing as already shipped.

Your remit is to make the platform diagnosable and safe to operate **without accessing claim content**. The technical-manager role is intentionally claim-blind. You own service health, instrumentation, sanitized logs, dashboards, alerts, technical runbooks, and operational release checks—not medical or insurance decisions, claim routing, adjudication, or SLM-generated clinical text.

## Private local synthetic credentials

Use **only the technical-manager account** for ordinary operator testing. All accounts belong to clinic ID `clinic-legacy-demo` and only exist in this local synthetic database. These are not production identities. Rotate or delete them before sharing a database, exposing services beyond localhost, or recording a public demo.

| Demo role | Email | Password | Purpose |
| --- | --- | --- | --- |
| Technical manager | `technical.local@claimguard.test` | `OBn0RijjEuJEKgvat7vK9ubaIN7QqxQe` | Your normal sign-in; claim-blind operations pages |
| Clinic admin | `admin.local@claimguard.test` | `hSxAc5KMzp3sBHOxY1uNL3y2ahtexu2A` | Supervised synthetic cross-role smoke checks only |
| RCM lead | `lead.local@claimguard.test` | `LG6G2SXMv49FdtLWNz84aVSbSiIKgFfb` | Synthetic assignment/workload comparison |
| RCM reviewer | `reviewer.local@claimguard.test` | `KL0vTWS/mvuFuN5ltWdiCzMY2QxnUOdg` | Synthetic claim workflow comparison |

The session-signing key and database credentials are in the local gitignored `.env`; **do not copy them into this document or Grafana provisioning**. The Grafana image's built-in `admin/admin` login is a development default from upstream, not a ClaimGuard user account. If you start that container, change its password before any shared use and keep its ports bound to localhost during development.

## First walkthrough: run and understand the app

### Preferred reproducible path: Compose

From the repository root, first confirm the working tree and agree on the baseline with the owner. Keep `.env` private. It must contain a random `CLAIMGUARD_SESSION_KEY` of at least 32 bytes. `docker-compose.yml` supplies the container-to-container database URL and rule catalogue path.

```powershell
git status --short
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 migrate
```

The non-Temporal services are `db` (PostgreSQL 16), one-shot `migrate`, `api`, `web`, and `otel-lgtm`. `migrate` runs `alembic upgrade head` before `api` becomes ready. Temporal is an optional infrastructure spike (`--profile temporal`) and is **not wired into claim processing**. Do not enable it merely to demonstrate monitoring.

Check these addresses after startup:

| Address | Expected use |
| --- | --- |
| `http://127.0.0.1:3001` | Next.js clinic application |
| `http://127.0.0.1:8000/v1/health` | API readiness JSON; check the body, not only HTTP 200 |
| `http://127.0.0.1:8000/docs` | FastAPI OpenAPI reference |
| `http://127.0.0.1:3000` | Grafana development sandbox; **no app telemetry until instrumented** |

`/v1/health` intentionally returns HTTP 200 even when its JSON says `degraded`; Compose's API health check parses `status`. For manual checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/v1/health | ConvertTo-Json
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 web
```

If you develop the API on the Windows host instead of Compose, use the repository's Python environment and load `CLAIMGUARD_SESSION_KEY` into the process environment first: the API reads that particular key from `os.environ` directly. Pydantic does read the rest of `.env`, but this key is an exception. Start `uv run claimguard serve --reload` from the root; then `cd frontend`, run `npm ci` once and `npm run dev -- --port 3001`. The frontend proxy targets `http://127.0.0.1:8000` unless `CLAIMGUARD_API_ORIGIN` is set. Do not run a second API on an occupied port or point the browser at a stale backend.

### In-app technical-manager tour

Go to `http://127.0.0.1:3001`, enter clinic ID and the technical-manager credentials above. The sidebar has:

| Page | What is truly available now | API |
| --- | --- | --- |
| Operations | API/database/schema/rule-catalogue readiness snapshot; Refresh button | `GET /v1/operations` |
| Intake Jobs | Per-clinic counts by job status, not source documents | `GET /v1/intake-jobs/operations` |
| Model & Rule Versions | Active rule version, current explanation-provider class, and versions observed on stored runs | `GET /v1/versions` |
| Redacted Logs | Recent intake job ID, status, error code, timestamp; **not server logs** | `GET /v1/redacted-logs` |
| Audit Integrity | Shared append-only chain verification plus clinic event count; no audit contents | `GET /v1/audit-integrity` |
| Configuration | Working, tenant-scoped `intake_enabled` toggle | `GET/POST /v1/configuration` |

The technical account must receive **403** from `GET /v1/queue`, `GET /v1/intake-jobs`, and claim-content endpoints. That is a required safety test, not a missing feature. Switching off intake is a real operational action: coordinate with the team, then switch it back on after a synthetic test. The technical manager is not allowed to inspect raw drafts, findings, requests, or patient/member data.

### When someone reports a bug today

1. Record **time, environment, affected page, expected behavior, observed behavior, and a safe correlation ID if available**. Do not ask for patient names, claim screenshots, document uploads, credentials, or raw browser cookies in a ticket.
2. Check `/v1/health` JSON, then Operations and the relevant technical page. Distinguish a schema/rule-readiness problem from a Next proxy problem, rejected JSON intake, or an SLM fallback. A 403 on claim content for the technical account is expected.
3. In Compose, inspect `docker compose ps` and bounded `docker compose logs --tail=100 api` / `web` / `migrate`. Current Uvicorn output is not a vetted redacted log store; review locally and **do not paste potentially sensitive lines into tickets or Grafana**. The in-app Redacted Logs page only covers intake statuses.
4. Reproduce with a **synthetic** fixture and write a minimal test. If a claim-rule or review decision differs, hand the case to the owner/reviewer-engine team; do not alter a rule to quiet an alert. If an audit-chain check fails, stop further state-changing experiments and escalate immediately—never “repair” the ledger by editing rows.
5. Record the cause, fix or mitigation, tests, and post-fix health evidence. For an intake outage, coordinate a temporary `intake_enabled=false` change with the clinic owner and record when it was restored. There is no general maintenance mode or alerting integration yet.

## Architecture and tenant model

The browser uses Next.js `frontend/src/app/workspace/[page]/page.tsx` and `ClinicPortal`. Its server-side `/v1/[...path]` proxy forwards the signed session cookie to the FastAPI service; it is **not** a second business API. FastAPI handlers in `claimguard/review/app.py` authorize the live role and call `ClinicDirectory`, `AssignmentStore`, `ReviewStore`, or `WorkspaceStore`. PostgreSQL stores immutable review evidence and the newer collaboration state.

One clinic equals one `tenant_id`. A user is global, but access is through an active `clinic_memberships(tenant_id, user_id, role)` row. The HMAC-signed, eight-hour HttpOnly session contains user and tenant IDs, not the role; the API resolves the role on **every request**. The server, not a hidden sidebar link, enforces permissions. `technical_manager` has only `READ_OPERATIONS` and `MANAGE_OPERATIONS`; `clinic_admin` has broad clinic access; reviewer and lead have review permissions. See `claimguard/clinic/access.py` before changing any route.

### Database map

| Schema area | Main tables | Meaning / rule |
| --- | --- | --- |
| Identity & tenancy (`0005`, `0007`) | `clinics`, `users`, `clinic_memberships`, `clinic_departments` | Clinic directory, active membership, local password hashes. Do not put credentials in telemetry. |
| Review evidence (`0002`, `0003`, `0004`, `0006`) | `rule_runs`, `rule_results`, `run_explanations`, `review_decisions` | Tenant-owned immutable claim versions, 15-rule results, bounded AI provenance, human decisions. `tenant_id` is non-null; key child tables have `(tenant_id, run_id)` FKs. |
| Assignment (`0008`) | `claim_assignments` | One current reviewer per `(tenant_id, claim_id)`; reassignment changes reviewer visibility. |
| Collaboration & intake (`0009`, `0010`) | `clinic_requests`, `clinic_escalations`, `intake_jobs`, `clinic_configuration` | Tenant-owned notes/escalations, validated JSON intake-job status, intake toggle. `0010` adds tenant/run FKs to job and collaboration rows. |
| Audit (`0001` onward) | `audit_events`; `verify_audit_chain()` | Append-only SHA-256-linked shared ledger. Never update, delete, or truncate it. Integrity verification is shared across tenants; the technical page shows only a boolean and count. |
| Earlier foundation (`0001`) | `claim_packages`, `canonical_claims`, `findings`, `finding_evidence` | Historical foundation tables; do not treat them as the current tenant-aware reviewer API's source of truth. |

The `claimguard` PostgreSQL schema is advanced by Alembic's ordered SQL migrations in `claimguard/db/migrations/versions/`. **Add a new migration; do not edit a migration already applied to a shared DB.** Operational reporting must not query raw claim tables from Grafana. Application-level tenant filtering and composite FKs exist, but a non-owner runtime DB role with RLS/equivalent isolation is still a release gate. The current local app DB connection has more privilege than a future production runtime should have.

The reviewer JSON transport remains frozen at **17 keys** and rule results at **15 keys**. SLM explanation/correction text is advisory and guarded; JEV is not in the claim pipeline. Telemetry must not alter deterministic results, review decisions, provenance receipts, or the audit ledger to make dashboards easier.

## Your implementation assignment: operations without claim leakage

### P0 — baseline and safety contract

1. Obtain the reviewed clinic-workspace baseline from the owner before branching. Work under a `codex/`-prefixed branch unless the team has agreed another naming convention. Keep this private guide and `.env` out of commits.
2. Reproduce `docker compose up -d --build`, verify readiness JSON, test technical login and the six pages, and record any differences from this guide. Test with synthetic data only.
3. Write a brief telemetry data classification table: **allowed** = service name, route *template*, status class, duration, queue/job counts, rule/model version, bounded error code; **forbidden** = request/response body, raw URL path/query, claim/run/patient/member/user identifiers, emails, cookies, authorization headers, file names, free-text exception messages, SQL parameters. Treat stack traces as potentially sensitive until scrubbed.

### P1 — instrument the real services

Use the existing `otel-lgtm` service as a **local development/test backend**, not production infrastructure. Choose OpenTelemetry Python SDK plus narrowly scoped FastAPI/SQLAlchemy instrumentation or manual spans; instrument Next.js only where it adds server-side signal. Export OTLP/HTTP to `otel-lgtm:4318` from Compose (or `127.0.0.1:4318` from a host process). Do not confuse the currently unused `CLAIMGUARD_OTEL_ENDPOINT` setting with a live exporter. Keep the exporter optional: if Grafana/OTLP is down, claim checking must still work and tests must not make network calls by default.

Start with a small, agreed metric set:

| Proposed metric | Type | Low-cardinality dimensions |
| --- | --- | --- |
| `claimguard_http_requests_total` | Counter | service, route template, method, status class |
| `claimguard_http_request_duration_seconds` | Histogram | service, route template, method |
| `claimguard_intake_jobs_total` | Counter | outcome/error code category |
| `claimguard_claim_checks_total` | Counter | outcome category; **no claim ID** |
| `claimguard_explanation_fallbacks_total` | Counter | reason category; **no prompt text** |
| `claimguard_db_operation_duration_seconds` | Histogram | fixed operation name, outcome |

These names are **proposals**, not existing endpoints or data. Validate semantics with the owner before implementation. Use fixed route templates (`/v1/runs/{run_id}`), never concrete paths. Do not use `tenant_id`, `claim_id`, `run_id`, email, or filename as metric labels: cardinality and privacy both suffer. Initially prefer aggregate, claim-blind operational metrics. If per-clinic operations become essential later, design a separate authorized aggregate API with explicit tenant scoping rather than adding tenant labels everywhere.

### P2 — sanitized logs, correlation, and useful dashboards

Create structured **allowlisted** operation events and a request-correlation ID; avoid generic auto-capture of bodies, headers, SQL binds, or exception `str()`. A redaction processor is defense in depth, not permission to collect sensitive fields first. Send sanitized logs to Loki through the OTLP pipeline and traces to Tempo. Build a Grafana dashboard as versioned configuration with panels for API availability, HTTP 5xx/rate and p95 latency, database readiness, intake reject rate, explanation fallback rate, and audit-chain integrity. Link from the technical workspace to a separately authenticated Grafana view only after access is configured; do **not** iframe an admin Grafana session or give Grafana access to the claim database.

The existing `Redacted Logs` page may be renamed to “Intake Events” or extended with a new, explicitly safe backend endpoint. Do not quietly change its JSON shape or pass Loki directly to the browser. Keep the FastAPI role boundary and the Next `/v1` proxy as the integration point. If you need an API change, define a small response model, test 200 for technical manager and 403 for reviewer, and prove the payload cannot contain a synthetic canary patient string.

### P3 — alerts and incident response

Create alerts only after measuring a synthetic baseline; propose thresholds to the owner rather than hard-coding guesses. Minimum candidate conditions: health JSON `degraded`, API/web unavailable, rising 5xx or sustained p95 latency, database unavailable, migration mismatch, abnormal intake reject rate, explanation fallback surge, and `audit_integrity.intact=false`. Provide one-page runbooks for each: impact, safe checks, escalation contact, rollback/disable path, and recovery verification. Alert notifications must not include claim identifiers or clinical text. The intake toggle is a **clinic-scoped emergency control**, not a general kill switch.

### P4 — hardening for a later real-data pilot

Help implement or review a non-owner application DB role and tenant-aware RLS/equivalent policy, secured Grafana authentication, secret rotation, service access controls, backup/restore rehearsal, retention/deletion rules for telemetry, and incident/audit procedures. This is joint security/platform work and requires owner review. The existing `otel-lgtm` image is documented by Grafana as a development/demo/test backend; do not put it into a real PHI deployment as-is. The current Compose ports and default Grafana login are development conveniences, not safe public exposure.

## Integration and merge rules

- **Own:** a focused observability package/configuration, safe instrumentation hooks, Grafana provisioning/dashboards, operational tests, and technical runbooks. Keep changes to claim-processing functions minimal and reviewed.
- **Coordinate before editing:** `docker-compose.yml`, `.env.example`, `claimguard/review/app.py`, `frontend/src/components/clinic-portal.tsx`, and migrations. These are the shared integration seams being changed by the clinic-platform work.
- **Do not change without explicit agreement:** the 17-key claim contract, 15-key rule result contract, deterministic rule engine, audit hash-chain format/triggers, the reviewer decision state machine, tenant/role model, or clinic admin/reviewer UX.
- **New API convention:** `/v1/operations/*` or another agreed versioned path; authorize on the server with `Action.READ_OPERATIONS`/`MANAGE_OPERATIONS`; derive tenant from signed session, never a user-provided query parameter. Preserve the Next proxy boundary. Prefer additive response fields and a separate endpoint over silently repurposing an existing page.
- **Migration convention:** additive migration after `0010`, with tenant-aware keys where applicable; no raw observability write into review tables; no destructive migration on synthetic shared data without owner approval.
- **PR evidence:** screenshot of a real non-empty synthetic dashboard, exact run commands, a 403 claim-access check, a canary-leak check across metrics/logs/traces, failing-collector resilience test, migration/test results, and any remaining security risks. Never include credentials, `.env`, raw claim bodies, or this guide.

## Definition of done for your first PR

A fresh agreed checkout starts; Grafana shows **actual** ClaimGuard metrics after synthetic API traffic; at least one sanitized log event and trace are queryable; collector failure does not fail claim processing; the technical-manager account can see safe operations but gets 403 for claim content; a deliberate canary claim string is absent from exported telemetry; the new UI/API contract has tests; and setup plus troubleshooting are reproducible from a short runbook. If only infrastructure is ready, label it honestly as infrastructure and do not claim observability is connected.

## Source references for the proposed monitoring approach

- Grafana's `otel-lgtm` project: development/demo/test scope, bundled OTLP backend, local ports, and provisioning examples: https://github.com/grafana/docker-otel-lgtm
- OpenTelemetry Python instrumentation: https://opentelemetry.io/docs/languages/python/instrumentation/
- OpenTelemetry sensitive-data handling: https://opentelemetry.io/docs/security/handling-sensitive-data/
- Prometheus metric-label cardinality guidance: https://prometheus.io/docs/practices/naming/ and https://prometheus.io/docs/practices/instrumentation/
- Grafana configuration-file provisioning: https://grafana.com/docs/grafana/latest/administration/provisioning/
- Grafana security warning that Viewers can query data sources directly: https://grafana.com/docs/grafana/latest/setup-grafana/configure-security/

Questions or architecture changes should be brought to the owner **before** changing shared contracts. Your goal is a dependable, privacy-safe technical control plane—not a second way to browse claims.
