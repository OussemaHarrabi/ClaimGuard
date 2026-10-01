# ClaimGuard frontend

The frontend is the public product page and authenticated clinic workspace. It is built with Next.js 16, React 19, TypeScript, Tailwind CSS 4, Radix primitives, shadcn utilities, and Lucide icons.

[Back to the project README](../README.md)

## Run it

The API and migrated PostgreSQL database must be running first. From this directory:

```powershell
npm ci
npm run dev
```

Open <http://127.0.0.1:3000>. By default, the server-side proxy sends `/v1/*` to `http://127.0.0.1:8000`. Override it at runtime when required:

```powershell
$env:CLAIMGUARD_API_ORIGIN = "http://127.0.0.1:8030"
npm run dev
```

The Docker stack publishes the frontend at <http://127.0.0.1:3001> and sets the internal origin to `http://api:8000`.

`NEXT_PUBLIC_DEMO_MODE` exists for isolated interface work. Keep it `false` for integration and submission verification so missing APIs are not hidden by demonstration data.

## Routes

| Route | Purpose |
|---|---|
| `/` | Product landing page and workspace entry |
| `/workspace/home` | Authenticated role landing; redirects to the role's first authorized page |
| `/workspace/[page]` | Role-aware workspace page |
| `/v1/[...path]` | Same-origin proxy to the FastAPI `/v1` contract |

The frontend does not implement authorization. It renders the pages permitted by the authenticated session, while the backend independently authorizes every request.

## Role navigation

| Role | Pages |
|---|---|
| RCM reviewer | My Queue, Document Intake, Requests, Activity |
| RCM lead | Team Queue, Assignments, Escalations, Review Quality, plus reviewer pages |
| Clinic admin | Overview, All Claims, Assignments, Departments, Team & Access, Analytics, Audit |
| Technical manager | Operations, Intake Jobs, Model & Rule Versions, Redacted Logs, Audit Integrity, Configuration |

`Claim Workspace` is intentionally not a second queue page. A reviewer opens a selected run from **My Queue** or **Team Queue**, then works in the evidence desk.

## UX contract

The review screen should keep three questions visible and connected:

1. What failed?
2. Which submitted value proves it?
3. What can the reviewer change before rechecking?

Findings, evidence, and correction guidance must stay aligned. Human-readable labels should be shown before raw JSON pointers. The raw path is still available for auditability. A correction never mutates the previous run; the interface submits a new version for recheck.

Use the existing design tokens and reusable primitives before creating page-specific styling. Preserve keyboard operation, focus visibility, semantic labels, responsive behavior, loading states, empty states, and actionable error messages.

## API boundary

Client helpers are in `src/lib/`. Components call relative `/v1` URLs so browser cookies remain same-origin. The proxy in `src/app/v1/[...path]/route.ts` forwards methods, bodies, response status, content type, and session cookies to FastAPI.

Do not:

- bake an API address into browser code;
- trust a role or tenant supplied by the browser;
- reproduce backend rule logic in React;
- silently replace API failures with mock success;
- expose technical-manager users to claim content.

The live OpenAPI page at <http://127.0.0.1:8000/docs> is the source for exact payloads.

## Quality gates

```powershell
npm run lint
npm run typecheck
npm test
npm run build
```

Component tests use Vitest, Testing Library, and jsdom. Add a test when changing role navigation, API error behavior, correction/recheck behavior, or the evidence desk. The production build uses Next.js standalone output for the Docker image.

## Important files

| Path | Responsibility |
|---|---|
| `src/app/page.tsx` | Public landing page |
| `src/app/workspace/[page]/page.tsx` | Dynamic workspace route |
| `src/app/v1/[...path]/route.ts` | Runtime API proxy |
| `src/components/clinic-portal.tsx` | Authentication shell and role navigation |
| `src/components/review-workspace-app.tsx` | Evidence-first run review and correction flow |
| `src/components/document-intake.tsx` | Source upload and intake jobs |
| `src/lib/clinic-api.ts` | Typed browser-facing API helpers |

For the backend contract, see [the review API guide](../claimguard/review/README.md). For the full manual journey, see [the Phase 1 rehearsal](../docs/verification/PHASE1-HANDS-ON-REHEARSAL.md).
