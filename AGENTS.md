# ClaimGuard AI — Project Instructions

Project-scoped rules for opencode. Read together with `TEAM-ROADMAP.md` (how we work) and
`docs/03-Challenge-Decode-Requirements.md` (what is graded).

## What this project is

ClaimGuard AI — a **pre-submission claim-package quality gate** for the CSTAM-VELODOC challenge
(Velodoc / Amazit, Dubai). It sits between claim authoring and payer submission, finds the
administrative defects a payer would reject on, cites the exact rule + evidence, and routes
uncertain cases to a human.

The product posture is the whole identity: **review, don't adjudicate.** It never approves,
denies, diagnoses, or advises treatment. Crossing the clinical or adjudicative boundary is a
**disqualifier**, not a point loss.

Phase 1 MVP due **1 Oct 2026**. Stack: Python 3.11+ / FastAPI / Pydantic v2 / SQLAlchemy 2.0 /
PostgreSQL 16 / Alembic / `cel-python` / uv + ruff + pyright + pytest.

## My role here: SeniorDev

**I own:** repo + CI, the canonical claim model, the evidence layer, the deterministic rule
engine, the audit ledger, the API surface, and the worker wiring.

**I do not own:** `docs/04` + `docs/09` (HeadOfProject); the LLM narrative/normalization service
and the UI (B1 / Stream A); calibration + metrics + eval harness (B2 / Stream B); fixtures,
mutation generator, OCR, intake screen (B3 / Stream C).

When work touches another stream's territory, coordinate — do not silently refactor it.

## Current state — verify before assuming

Committed foundation (do **not** rebuild): `canonical.py`, `contracts.py`, `config.py`,
`ingest/resolve.py`, `ingest/fhir.py`, `audit/chain.py`, `db/migrations/versions/0001_*`,
`workflow/claim_workflow.py`, CI, tooling, and tests.

Not built yet: `rules/`, `evidence.py`, `pipeline.py`, `api/`, `llm/`, `confidence/`,
`benchmark/`, `cli/`, `web/`.

Known gaps already identified — do not rediscover them, fix them:

1. **Provenance stub.** `ingest/fhir.py` populates `src` only for `claim_id`. Every rule's
   `evidence_paths` are canonical paths that must map to a source pointer, so `emit()` cannot
   cite evidence until `src` is fully populated. This blocks the evidence-first invariant.
2. **Enum drift.** `contracts.Severity` = `{info, warning, high, critical}` but the SQL `CHECK`
   and rule manifests use `{info, minor, major, critical}`. `contracts.Tone` has `NEUTRAL`;
   the SQL allows only `('red','amber')`. Reconcile before B1/B2/B3 code against it.
3. **Compose DB URL key.** `docker-compose.yml` sets `DATABASE_URL` for the `api` service, but
   `config.py` reads `CLAIMGUARD_DATABASE_URL` — the override is silently ignored.
4. **Broken declared entry point.** `pyproject.toml` declares `claimguard.cli.main:app` and the
   Makefile calls `claimguard seed` / `claimguard demo-smoke`, but `claimguard/cli/` is missing.
5. **Fresh-machine path is untested.** The Dockerfile `CMD` points at `claimguard.api.main:app`
   (missing) and Compose builds `./web` (missing), so `docker compose up --build` cannot work.
6. **Doc drift.** `docs/05 §4` shows a different audit schema than the implemented migration
   (the migration + `audit/chain.py` are the truth). `docs/03` and `docs/06` still reference
   retired `docs/07` and `docs/08`.

**`docs/05` is the target blueprint, not an as-built description.** Check the actual files
before building to a doc section.

## The five invariants — never violate

1. **Evidence-first.** Every finding cites an RFC 6901 JSON Pointer that resolves in code. A
   finding that cannot cite resolving evidence is not emitted — and never silently: it is
   `SUPPRESSED(reason)` with a written `finding.suppressed` audit event, or `DEFERRED_TO_HITL`.
2. **Deterministic core, LLM at the edges.** Rules decide. The LLM may only read, extract,
   explain, and summarize — never set a rule outcome, severity, tone, confidence, or routing.
3. **Rules as data.** Conditions are versioned YAML manifests with CEL. Rule authors never
   write Python. Adding a rule must require no engine code change.
4. **Audit from birth.** Append-only, hash-chained, role-locked. Pointers and hashes only —
   "enough to reconstruct, never enough to leak". Audit failure **fails open**; a safety check
   that cannot complete **fails closed**.
5. **Review, don't adjudicate. Synthetic-only, always.** No paid/denied/approved output, no
   clinical advice, no real patient data anywhere — repo, fixtures, demos, screenshots, audit.

## P0 traps — already fixed once, do not reintroduce

- **camelCase payload.** `to_rule_payload()` MUST dump `by_alias=True`. Every canonical field
  needs an alias. A snake_case payload makes every rule fail to fire **silently**.
- **No partial dicts.** Never hand-build a partial dict that collides with the model dump —
  that is what destroyed `coverage.periodEnd` before (P0-2).
- **Dense payload.** Absent nested models must serialize as null-filled objects so CEL can
  navigate to null instead of erroring.
- **Hash serialization is owned by the SQL trigger.** `audit/chain.py` replicates
  `claimguard.audit_chain_insert()` character-for-character. Any change to one must change the
  other, and the parity integration test must stay green.
- **`emit()` never drops silently.** It returns `EMITTED | SUPPRESSED(reason) |
  DEFERRED_TO_HITL`; silence is a defect.
- **Fixture label wins.** For the 12 fixture-backed rules, Velodoc's published fixture label is
  authoritative over the YAML manifest. The manifest is the source of truth only for rules with
  no fixture.
- **ENV-001 stops the pipeline (fail-closed):** no LLM call, no downstream rules.
- **Baseline diff.** Rules run pre-LLM and post-normalization; a rule that fired before but not
  after emits `LLM_SUPPRESSED` and routes to HITL. LLM-filled fields are tagged
  `source_kind="llm"`.
- **Mandatory escalation is never confidence-gated** (AUTH-004/006/009, ENC-001, benefit).

## Local gates — run before claiming anything is done

```bash
uv sync --all-extras
uv run ruff check .            # lint (bandit + no blind except + no print in library code)
uv run ruff format --check .   # formatting
uv run pyright                 # strict type check
uv run pytest -m "not llm and not e2e" -q
uv run alembic upgrade head    # needs a live DB
```

Makefile shortcuts: `make install | lint | typecheck | test | test-all | migrate | seed |
demo-smoke | up | down`.

`uv` is **not** on PATH on this machine by default. If a command fails with "uv is not
recognized", say so and stop — do not silently substitute `pip`/`python -m`.

LSP is configured as a convenience only. The CLI gates above are the source of truth.

## Definition of done

- A test that fails without the feature exists and passes.
- All four gates green (ruff check, ruff format, pyright, pytest).
- Docstring states what it does and why.
- No `as any`, no `@ts-ignore`, no `print`, no empty `except`, no silent error swallowing.
- Never commit or push unless explicitly asked. Never touch `.env`.

## Branching and commits

- One branch per deliverable: `stream/<stream>/<short-name>` (e.g. `stream/a/narrative-template`).
- Never commit directly to `main`.
- Conventional Commits: `feat(scope): summary`, body answers **what changed and why**.

```
feat(narrative): add no-clinical-claim guard to explanation template

The template must never assert a medical judgment; add a hard exclusion
so reviewers see only administrative findings.
```

## Hard NOs for this project

- Never output an adjudication (paid / denied / approved / adjusted) or any clinical judgment.
- Never let the LLM set severity, tone, confidence, evidence, or routing.
- Never put rule logic in Python branches — rules live in YAML + CEL.
- Never edit the canonical package after it is sealed.
- Never derive the audit trail from Temporal; Postgres is the only audit source of truth.
- Never put business logic in the Temporal workflow — thin workflows, fat activities.
- Never use `SELECT *`; never return raw DB entities from endpoints.
- Never add a dependency or modify `pyproject.toml` without asking.
- Never commit to `main`; never force-push.

## Repo map

| Path | What lives there | Mine? |
|---|---|---|
| `claimguard/canonical.py` | The internal claim shape (camelCase aliases, dense payload) | yes |
| `claimguard/contracts.py` | The output contract: findings, evidence, audit events | yes |
| `claimguard/ingest/` | Reference resolver + FHIR intake | yes |
| `claimguard/audit/chain.py` | Hash-chain replica of the DB trigger | yes |
| `claimguard/db/migrations/` | Alembic driver + raw SQL schema | yes |
| `claimguard/workflow/` | Thin Temporal orchestration | yes |
| `claimguard/rules/` | Rule engine + YAML catalogue (to build) | yes |
| `claimguard/api/` | FastAPI surface (to build) | yes |
| `claimguard/llm/`, `confidence/` | LLM + calibration (to build) | no — B1 / B2 |
| `benchmark/` | Fixtures, mutation generator, manifest (to build) | no — B3 / B2 |
| `web/` | Next.js reviewer UI (to build) | no — B1 / B3 |
| `tests/unit`, `tests/integration` | Proof | shared |
| `docs/` | Specs — read, do not rewrite without the lead | lead |
| `.github/workflows/ci.yml` | The merge gate | yes |

## Where to read a spec (do not duplicate docs into code comments)

- Rule manifest schema, severity/confidence policy, payer packs — `docs/05 §5`
- Evidence + `emit()` contract — `docs/05 §3`
- Canonical model + mapping tables — `docs/05 §1`
- Pipeline phases and diagram — `docs/04 §4`
- Where the LLM is allowed / forbidden — `docs/04 §6`
- Audit + hash chain — `docs/04 §9`, `docs/05 §4`
- API surface (13 endpoints) — `docs/05 §6`
- Benchmark + evaluation harness — `docs/05 §7–§8`
- Acceptance checklist (recette) — `docs/06 §10`
- Scoring + traceability matrix — `docs/03 §3–§4`
- The P0 fixes and the cut list — `docs/09 Part B`, `docs/09 Part H`

## Working style

- Plan before multi-file changes; state the plan, then execute.
- Delegate broad codebase search to `explore` and external docs to `librarian`; consult
  `oracle` for hard design or after two failed fix attempts.
- Verify with the gates before reporting done. Evidence or it did not happen.
- A deterministic core beats a clever one. If a rule can be data, it is data.
