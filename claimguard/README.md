# ClaimGuard Python application

This package contains the FastAPI backend, deterministic validation engine, clinic platform, bounded assistance, audit primitives, migrations, workflows, and command-line tools.

[Back to the project README](../README.md)

## Package map

| Package | Owns | Guide |
|---|---|---|
| `edu` | The authoritative 15-rule Phase 1 engine, evidence, normalization, deterministic explanations, JEV sidecar | [Engine guide](edu/README.md) |
| `review` | FastAPI application, endpoint models, workflow orchestration, persistence | [Review API guide](review/README.md) |
| `clinic` | Identity, sessions, tenancy, RBAC, assignments, intake, workspace read models | [Clinic guide](clinic/README.md) |
| `ai` | Bounded interactive-assistant graph, provider, tools, schemas, receipts | [AI guide](ai/README.md) |
| `audit` | Canonical hash-chain computation and verification | [Audit guide](audit/README.md) |
| `db` | Alembic runtime and SQL migrations | [Database guide](db/README.md) |
| `cli` | `claimguard` operator and evaluation commands | See `claimguard --help` |
| `ingest` | Earlier common ingest helpers used by the project | Source-level module documentation |
| `workflow` | Workflow definitions and future durability seam | Source-level module documentation |

Shared top-level modules include `contracts.py` for boundary types, `canonical.py` for canonical data helpers, and `config.py` for application settings.

## Dependency direction

The deterministic engine must remain usable without an API, database, browser, or model provider. The review application may call the engine, clinic services, audit, and AI orchestration. The AI package may read a bounded projection of persisted facts but may not call back into mutation paths or alter deterministic results.

```text
CLI / Next.js
      │
      ▼
 FastAPI review layer
   │      │       │
   ▼      ▼       ▼
clinic   edu      ai
   │      │       │
   └──────┴───────┘
          ▼
   store / PostgreSQL / audit
```

Keep imports acyclic and keep external-service clients outside the deterministic rule path.

## Configuration

Settings are environment-driven. Copy the commented root `.env.example`; never create a second undocumented environment contract inside a subpackage. Important groups include:

- `CLAIMGUARD_DATABASE_URL`
- `CLAIMGUARD_SESSION_KEY`
- `CLAIMGUARD_RULES_DIR` or `CLAIMGUARD_PACK_ROOT`
- `CLAIMGUARD_AI_*` for the interactive assistant
- `CLAIMGUARD_TYPESAFE_*` and `CLAIMGUARD_JEV_*` for the optional JEV sidecar

Model and JEV settings are optional. Database, migrations, catalogue, and session signing are required for the protected product API.

## Development gates

```powershell
uv run ruff check claimguard tests
uv run ruff format --check claimguard tests
uv run pyright
uv run pytest -m "not llm and not e2e"
```

When changing a package, read its local README and add tests at the closest boundary. Integration tests belong under `tests/integration`; do not turn every unit test into a database test.
