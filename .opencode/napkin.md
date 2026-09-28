# ClaimGuard — napkin (project memory)

Persistent memory for opencode sessions on this repo. Read at session start, update at session
end. Keep it short: state, decisions, gotchas, next actions — not a doc dump.

**Role in this repo:** SeniorDev. **Last updated:** 2026-09-15.

## State (verified 2026-09-15)

- Git: `main`, clean working tree, 7 commits — **all authored by Oussema Harrabi (HeadOfProject)**,
  including the 16,938-line foundation commit that contains the senior's own files.
- Committed foundation: `canonical.py`, `contracts.py`, `config.py`, `ingest/resolve.py`,
  `ingest/fhir.py`, `audit/chain.py`, `db/migrations/` (env.py + `0001_initial_schema.sql`),
  `workflow/claim_workflow.py`, CI, tooling, `tests/unit` + `tests/integration`.
- **Missing:** `claimguard/rules/`, `evidence.py`, `pipeline.py`, `api/`, `llm/`, `confidence/`,
  `benchmark/`, `cli/`, `web/`.
- Sprint position: **S2 (14–20 Sep)** = engine core. Demoable target: `CLM-0042 → 3 findings +
  audit rows`. Hard feature freeze **27 Sep**. MVP submit **1 Oct**.

## Environment

- `uv` is **not** on PATH on this machine. Gates cannot run until it is installed.
- `python` resolves to MSYS2 3.12.7; `pyproject.toml` allows 3.11–3.13.
- Shell is inconsistent (bash vs PowerShell) — avoid `foreach`/`$var` in bash tool calls; prefer
  simple commands or the dedicated tools.

## Decisions / facts

- `docs/05` is a **target blueprint, not as-built**. Check files before building to a section.
- `docs/04`/`09` owned by HeadOfProject; `docs/05`/`04` co-owned; `docs/07`/`08` retired.
- The SQL trigger owns the audit hash serialization; `audit/chain.py` replicates it exactly.
- Fixture label > YAML manifest for the 12 fixture-backed rules.
- Failed background subagents once with "Insufficient balance" — do exploration inline if it recurs.

## Gotchas found (fix, do not rediscover)

1. `ingest/fhir.py` populates `src` only for `claim_id` → **evidence-first is unimplementable**
   until provenance is complete. Highest-priority blocker.
2. `contracts.Severity` `{info,warning,high,critical}` vs SQL `CHECK` `{info,minor,major,critical}`;
   `contracts.Tone` has `NEUTRAL`, SQL allows only `{red,amber}`. Writes will be rejected.
3. Compose sets `DATABASE_URL` for `api` but `config.py` reads `CLAIMGUARD_DATABASE_URL`.
4. `pyproject.toml` declares `claimguard.cli.main:app`; `claimguard/cli/` does not exist →
   `make seed` / `make demo-smoke` fail.
5. Dockerfile `CMD` → `claimguard.api.main:app` (missing); Compose builds `./web` (missing) →
   `docker compose up --build` cannot work.
6. `docs/03` and `docs/06` still cite retired `docs/07`/`08`.

## Open questions for the HeadOfProject

1. Severity/tone: which side is authoritative? Propose reconciling to
   `{info, minor, major, critical}` + `neutral`.
2. Sprint plan: `docs/09` calls `07`/`08` canonical but they were retired — re-anchor in
   `TEAM-ROADMAP.md`?
3. Ownership: is the committed foundation mine to own/extend, or a bootstrap to review?
4. `docs/05`: stop claiming "implemented-as-is", or build to it? Propose splitting as-built vs target.

## Next actions (S2)

1. P1.1 Freeze contracts (enums, `__init__.py`, Compose env key) — unblocks everyone.
2. P1.2 Populate `src` provenance + write `claimguard/evidence.py` (`resolve_pointer`, `emit`).
3. Spike `cel-python` on the DUP-002 `exists` macro **before** writing the loader.
4. P1.3 Rules: manifest validator → loader + dense-payload smoke test → engine → ENV-001 → the 4
   flagship YAML rules (COV-001, AUTH-004, DUP-002, ENV-001).
5. P1.4 `pipeline.py` facade (`validate_package() -> ValidationReport`) + `cli/main.py`.
6. P1.5 Fixture on disk: `benchmark/seed/fixtures/CLM-0042/` + `universe.yaml` + manifest models.
7. P1.6 Migration 0002 (rule_catalogue, review_tasks, review_decisions, explanations, llm_calls,
   calibration_runs, benchmark_*).
8. P1.7 CSV intake (`ingest/csv.py`) for FHIR↔CSV equivalence (recette R1.1).

## Stream go-signals

- **B3 / Stream C (fixtures, OCR, mutation gen):** starts coding immediately; needs only the
  canonical model + resolver (frozen) and the `benchmark/seed/` layout (P1.5).
- **B1 / Stream A (LLM narrative):** may build the template + verifier against `contracts.py`
  after P1.1; end-to-end wiring after P1.3/P1.4.
- **B2 / Stream B (metrics):** toy metrics module now; harness after P1.4 + P1.5.

## Tools configured for this repo

- Project config: `opencode.json` (permissions, LSP, formatter, `gates` / `spec-audit` /
  `engine-smoke` commands).
- Subagents: `claimguard-invariant-reviewer`, `claimguard-spec-auditor`.
- Project rules: `AGENTS.md`.
