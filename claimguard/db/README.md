# PostgreSQL schema and migrations

ClaimGuard uses PostgreSQL 16. Alembic runs ordered SQL migrations from `migrations/versions/`; the Compose `migrate` service applies them before the API becomes ready.

[Back to the project README](../../README.md)

## Run migrations

```powershell
docker compose up -d db
uv run alembic upgrade head
uv run claimguard status
```

The application DSN is `CLAIMGUARD_DATABASE_URL`. Compose overrides the host name to `db` inside containers. Do not hardcode a developer DSN in source.

## Schema areas

| Area | Main tables |
|---|---|
| Canonical claim and findings | `claim_packages`, `canonical_claims`, `findings`, `finding_evidence` |
| Versioned review | `rule_runs`, `rule_results`, `review_decisions`, `run_explanations` |
| Clinic identity | `clinics`, `users`, `clinic_memberships`, `clinic_departments` |
| Work management | `claim_assignments`, `clinic_requests`, `clinic_escalations`, `intake_jobs`, `clinic_configuration` |
| Assistant | `assistant_threads`, `assistant_turns` |
| Integrity | `audit_events` and protected-history triggers |

Migrations `0001` through `0011` build the current schema. `0006` adds tenant ownership to review records; `0010` adds workspace tenant constraints; `0011` adds assistant history.

## Data invariants

- Historical runs, results, decisions, explanations, assistant turns, and audit records are append-oriented or trigger-protected.
- Tenant-owned relationships must include the tenant key, not only a globally shaped record ID.
- A correction creates a new run version and links to the preceding run.
- The API must scope queries by the authenticated tenant.
- Schema readiness is exposed by `/v1/health` and `claimguard status`.

The schema has tenant columns and relational constraints, but PostgreSQL row-level security is not yet enabled. That is a planned defense-in-depth layer, together with a non-owner runtime account.

## Writing a migration

1. Add the next ordered SQL file under `migrations/versions/`.
2. Make forward application deterministic and safe on a current database.
3. Preserve protected history and existing tenant ownership.
4. Update SQLAlchemy table metadata and store queries in the same change.
5. Add migration and integration tests.
6. Test both a fresh database and upgrade from the previous revision.

Do not edit an already-shared migration to change history. Add a new migration.

## Local reset warning

`docker compose down` preserves the named volume. Removing the volume destroys local database contents and should only be done deliberately after confirming that no local evidence or work is needed.
