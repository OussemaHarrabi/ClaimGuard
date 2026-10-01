# Product frontend refresh — 1 October 2026

## Scope

Adminator-inspired admin/RCM interface and a separate product landing page, keeping the existing ClaimGuard navy/blue/aqua palette and Next.js implementation. Reference: https://github.com/puikinsh/Adminator-admin-dashboard (public README screenshots inspected). No template assets/code copied; no dependency added. Technical-manager pages and backend/database contracts are outside this change.

See `PHASE-1-SUBMISSION-READINESS.md` for the official-book comparison and remaining submission work.

## Implementation

- Public landing at `/`; sign-in/role home at `/workspace/home`.
- Light business sidebar/topbar, persisted desktop collapse preference and responsive mobile drawer.
- Admin overview/analytics powered by the existing `/v1/analytics` API, with real counts, check-run activity, exact chart data and result totals. Rechecks count as runs, not new claims. Pending intake and requests are informational metrics explicitly owned by RCM workflows.
- Clearer review panels with queue filters, evidence, an explicit correction/recheck step, and explanation/provenance. At 1280px, queue, findings and guidance are visible side by side. Narrower screens stack panels without removing functionality.
- Search, sort, 12-row pagination and structured-detail disclosure for business report tables. Reference IDs are preserved exactly.
- Landing illustration is labelled; no false payer approval, fabricated clients or promised autonomous corrections.

## Fresh automated checks

Run from `frontend/`:

| Command | Result |
|---|---|
| `npm test` | 13 files, **46 tests passed** |
| `npm run lint` | Passed |
| `npm run typecheck` | Passed |
| `npm run build` | Passed; `/` static, workspace and API proxy dynamic |

New regression coverage checks dashboard API failure versus genuine zero counts, assignments routing, informational intake/request metrics, exact identifiers, table search and pagination. Tests of API consumers use controlled responses; they do not replace the live checks below.

## Live browser checks

Used the existing local API/database with synthetic demo accounts. No credentials are included here.

- Admin sign-in and overview populated: 16 distinct clinic claims, 4 assigned, 345 historical rule results at test time. These are local fixture counts, not performance or adoption claims.
- All Claims opened through mobile navigation; sidebar links received clicks after the backdrop stacking correction.
- Sidebar collapse/expand, loaded-queue state filter, and correction editor opening were exercised. The editor showed source fields and the new-version recheck action. **No correction was submitted in this iteration's browser session.**
- Reviewer sign-in displayed the assigned My Queue and rendered Activity records.
- Lead sign-in displayed Team Queue and a distinct My Queue. The personal queue showed two assigned claims; the team queue showed a broader set.
- Production-build lead Activity: moved to page 2 of 3, searched `review_decision`, and sorted Recorded at with `aria-sort=ascending`.
- Laptop 1280px screenshot confirmed the three review zones. Mobile 390px checks found no page-level horizontal overflow on overview/landing; navigation open, route click and close were checked.
- Live inspected claims correctly labelled their assistance **Deterministic wording**. This is not evidence that an SLM was serving these runs.

## Review fixes

An independent review identified a mobile stacking regression: a business-specific z-index put the sidebar below its backdrop. Browser hit-testing reproduced the obstruction; removing the override restored clickability. Review also caught the intake metric incorrectly linking to All Claims although pending drafts have no run yet. It is now informational and names its RCM owner. Follow-up review found both issues corrected with no important new regression.

## Limits and release notes

- Existing write APIs/correction behavior were retained, not comprehensively re-exercised against the database in this UI pass. Fresh focused backend regression checks: **344 passed**, documented in the readiness assessment.
- This is not a full accessibility certification, load test or cross-browser test. Keyboard focus management of existing dialogs and complete multi-role write-flow rehearsal remain release checks.
- The refreshed preview was verified on local ports 3002 (development) and 3003 (production build); these are temporary local processes, not a deployment. The older running port 3001 was not restarted. Use the new preview to inspect this iteration.
- This frontend iteration adds no database migration or public deployment. The unrelated local edit to `tests/edu/test_envelope.py` and the untracked `.repowise/` directory are outside this change.
- Private local handoff and credentials remain outside tracked documents.
