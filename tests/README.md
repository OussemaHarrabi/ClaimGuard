# Test suite

The test suite covers deterministic rules, intake projections, evidence, explanation guards, clinic tenancy and roles, review workflow, audit integrity, CLI behavior, frontend fallback behavior, experiments, and PostgreSQL integration.

[Back to the project README](../README.md)

## Daily test loop

```powershell
uv sync --all-extras
docker compose up -d db
uv run alembic upgrade head
uv run pytest -m "not llm and not e2e"
```

Useful focused runs:

```powershell
uv run pytest tests/edu tests/edu_edges tests/edu_intake
uv run pytest tests/review tests/clinic tests/ai
uv run pytest tests/integration
uv run pytest tests/cli
```

Frontend tests live next to components under `frontend/src` and run separately:

```powershell
Set-Location frontend
npm ci
npm test
```

## Markers

| Marker | Meaning |
|---|---|
| `unit` | Fast, no I/O or network |
| `integration` | Requires PostgreSQL and/or Docker |
| `e2e` | Full stack and slow; opt-in |
| `llm` | Calls a live provider; opt-in |
| `benchmark` | Evaluation harness run |

Pytest uses strict markers, strict configuration, importlib mode, warnings as errors, and branch coverage for `claimguard` outside the CLI package.

## Where tests belong

| Area | Directory |
|---|---|
| Rule behavior and envelope | `edu/`, `edu_edges/`, `edu_conformance/` |
| CSV and FHIR ingestion | `edu_intake/` |
| Explanation and model guards | `edu_explain/`, `ai/`, `judge/` |
| Clinic identity and tenancy | `clinic/` |
| API and review workflow | `review/`, `integration/` |
| Audit and reproducible scripts | `integration/`, `sample_run/` |
| CLI and reports | `cli/`, `edu_report/` |

## Required security cases

For each clinic-owned resource, test same-tenant success, cross-tenant refusal, insufficient role, and missing/invalid session. For assistant changes, test prompt injection in source text, contradicted evidence, prohibited authority claims, provider timeout, malformed output, and deterministic fallback. For corrections, test that the old run stays unchanged and the new run points back through `supersedes_run_id`.

Tests and generated metrics serve different purposes. A green unit suite is not proof of mentor-pack conformance; run the conformance and report commands before publishing Phase 1 numbers.
