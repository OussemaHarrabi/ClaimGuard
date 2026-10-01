# Review API and workflow

`claimguard.review` exposes the FastAPI application and coordinates validation, persistence, review decisions, correction, recheck, audit, clinic services, and the interactive assistant.

[Back to the project README](../../README.md)

## Run it

```powershell
docker compose up -d db
uv run alembic upgrade head
uv run claimguard serve --reload
```

Open <http://127.0.0.1:8000/docs> for the exact OpenAPI contract and <http://127.0.0.1:8000/v1/health> for readiness. A valid `CLAIMGUARD_SESSION_KEY` and a provisioned account are required for protected routes.

## Workflow

```text
source files
   │
   ▼
intake draft ── invalid ──► quarantine/reject, no rule execution
   │ accepted
   ▼
submit ─► immutable run ─► 15 results ─► assignment/queue
                                          │
                         ┌────────────────┼────────────────┐
                         ▼                ▼                ▼
                    decision       request info       escalation
                         │
                         ▼
                 correction editor
                         │
                         ▼
                  recheck as vN+1
                  supersedes vN
```

The original envelope, results, explanations, and decisions remain historical records. A recheck is a new run, not an update.

## API groups

| Group | Main routes |
|---|---|
| Identity | `/v1/auth/login`, `/v1/auth/me`, `/v1/auth/logout` |
| Claims | `/v1/claims`, `/v1/runs/{run_id}`, `/v1/runs/{run_id}/claim`, `/v1/runs/{run_id}/results`, `/v1/claims/{claim_id}/recheck` |
| Decisions and queues | `/v1/runs/{run_id}/decisions`, `/v1/queue`, `/v1/my-queue`, `/v1/assignments` |
| Clinic workflow | `/v1/team`, `/v1/departments`, `/v1/requests`, `/v1/escalations`, `/v1/intake-jobs` |
| Read models and operations | `/v1/activity`, `/v1/overview`, `/v1/analytics`, `/v1/review-quality`, `/v1/audit`, `/v1/operations`, `/v1/versions`, `/v1/redacted-logs`, `/v1/audit-integrity`, `/v1/configuration` |
| Assistant | `/v1/ai/status`, `/v1/runs/{run_id}/findings/{rule_id}/explain`, `/v1/threads/{thread_id}/messages`, `/v1/threads/{thread_id}` |

The API returns explicit HTTP failures for authentication, authorization, validation, conflict, or unavailable infrastructure. Frontend code should show those failures and suggested recovery; it should not convert them into mock success.

## Code map

| File | Responsibility |
|---|---|
| `app.py` | Application construction, middleware, route registration, handlers |
| `models.py` | API request and response models |
| `store.py` | PostgreSQL queries and transaction boundaries |
| `audit_events.py` | Workflow event recording |
| `explanations.py` | Explanation request orchestration and provenance |
| `ui/` | Legacy operational fallback at `/review` |

The primary user interface is the separate [Next.js frontend](../../frontend/README.md). The legacy interface is retained as a fallback, not a second product contract.

## Security rules

- Authentication middleware resolves the signed session before protected handlers run.
- Tenant and role come from the server-side principal.
- Store queries must be tenant-scoped before returning a record.
- Authorization must occur before claim content is loaded or included in an error.
- Technical managers may inspect operational and redacted metadata only.
- Assistant context is derived from records the caller may already read.
- Corrections and decisions are auditable append operations.

Current tenant enforcement is at the session/service/query and relational-constraint layers. Database row-level security is a future hardening task.

## Tests

```powershell
uv run pytest tests/review tests/clinic tests/ai tests/integration -m "not llm and not e2e"
```

PostgreSQL-backed tests require the database and current migrations. Prefer application-factory tests so configuration and provider failures can be exercised without import-time side effects.
