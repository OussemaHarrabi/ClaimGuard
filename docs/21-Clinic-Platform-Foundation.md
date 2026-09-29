# 21 — Clinic platform foundation and role workspaces

> Status (2026-09-28): functional **synthetic-data pilot**, not a production PHI release.
> The clinic workspaces use persisted, tenant-scoped APIs and real session-based role checks.
> Document intake currently accepts ClaimGuard JSON only; arbitrary PDFs and narrative extraction
> remain future work. No payer submission or adjudication is performed.

## Product boundary

One clinic is one tenant. Departments and staff belong to it. The RCM reviewer reviews assigned
or self-submitted claims; the RCM lead supervises and routes work; the clinic admin manages people,
departments, and clinic-wide reporting; the technical manager sees health and operational metadata,
never claim envelopes or findings. The Evidence Desk remains the core claim workspace.

## Implemented

- Migrations `0005`–`0010` create the clinic directory, credential hashes, tenant-owned review rows,
  assignments, requests, escalations, JSON intake jobs, and clinic operational configuration.
  Historical synthetic runs were assigned to `clinic-legacy-demo`; the frozen 17-key claim and
  15-key result contracts and immutable audit ledger remain unchanged.
- HMAC-signed eight-hour HttpOnly, SameSite=Strict sessions resolve **live** clinic membership on
  each request. Revoking a membership prevents further access. No default administrator is shipped;
  create one locally with `python -m claimguard.clinic.provision`.
- Review reads and writes are tenant-filtered. Admins and leads can assign clinic claims only to an
  active reviewer or lead in the same clinic. `My Queue` shows assigned and self-submitted claims.
  Run, explanation, decision, and recheck endpoints derive actor and tenant from the session.
- RCM reviewer pages: My Queue, Document Intake, Claim Workspace, Requests, Activity.
- RCM lead pages: Team Queue, Assignments, Escalations, Review Quality, plus reviewer pages.
- Clinic admin pages: Overview, All Claims, Assignments, Departments, Team & Access, Analytics,
  Audit. These read/write the database; Analytics and Audit are clinic-filtered.
- Technical manager pages: Operations, Intake Jobs, Model & Rule Versions, Redacted Logs, Audit
  Integrity, Configuration. These endpoints return health, counts, versions, status codes, and
  chain integrity only. Direct claim/draft/queue access is denied.
- Intake pilot: a reviewer uploads a ClaimGuard JSON document (64 KiB maximum). The API does not
  persist raw source text; it stores a SHA-256 digest and an extracted JSON draft. A person opens
  the draft before triggering the unchanged deterministic engine. Invalid JSON is recorded as a
  rejected job with an error code. This proves a bounded source → draft → reviewed claim path;
  it does **not** prove PDF/OCR or arbitrary clinical document understanding.
- Every new role page is connected to a real route. Empty states reflect an empty database, not
  mock records. The Next.js `/v1/*` proxy forwards only the ClaimGuard session cookie.

## Reproduce locally

1. Set a random `CLAIMGUARD_SESSION_KEY` in the private `.env` file. Do not commit the key.
2. Start PostgreSQL, run `alembic upgrade head`, then start the API and Next.js web app. Compose
   runs migration before the API when `docker compose up -d --build` is available.
3. Provision one clinic admin with `python -m claimguard.clinic.provision --tenant-id ...
   --clinic-name ... --email ...`; enter the password interactively. Use Team & Access to create
   reviewer, lead, and technical-manager accounts.
4. Sign in on the Next.js site and exercise each role. Use synthetic claims only.
5. Run `pytest tests/review tests/clinic -q`, `npm test`, `npm run typecheck`, `npm run lint`, and
   `npm run build` before recording the submission video.

## Known release gates

- The API currently relies on application-level tenant filtering. Add a non-owner runtime database
  role and tenant-aware row-level security or equivalent isolation before using real patient data.
- JSON intake is a format-specific pilot; dental invoice, visit note, eligibility/pre-authorization,
  imaging, and PDF/OCR extraction need a documented source schema, field-level provenance, conflict
  handling, human correction, and held-out evaluation. Never invent missing clinical facts.
- Requests and escalations are internal workflow notes, not external clinic messaging; no notification
  delivery or patient/payer communication exists yet.
- Improve authentication for deployment: SSO/invitations, password reset, login throttling, and CSRF
  review. The local credential path is for a synthetic demo only.
- The technical audit-integrity check validates the shared chain without showing contents. Define
  the operational ownership and incident response for a broken chain before production.
- The SLM explanation/correction layer remains advisory and must pass grounded, human-reviewed
  evaluation. Deterministic rule results and reviewer decisions are the authority. JEV is not yet
  in the claim pipeline; evaluate specific guarded intervention points separately.

## Submission sequence

For the 1 October first submission, record only the verified synthetic workflow; no pitch deck is
required. For later phases, harden isolation and identity, build genuine multi-document intake,
measure the SLM/JEV experiments, and refine usability, accessibility, and observability. Do not
use real patient information or payer integration until the security and data-protection gates have
been independently reviewed.
