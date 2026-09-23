-- =====================================================================
-- ClaimGuard — migration 0003: explanation provenance
--
-- revision = '0003'
-- down_revision = '0002'
--
-- Alembic-managed raw-SQL migration (see claimguard/db/migrations/env.py,
-- which parses the two identifiers above, applies pending files in
-- dependency order inside one transaction and records them in
-- alembic_version).
--
-- SCOPE
-- -----
-- ADDITIVE ONLY. This migration creates one NEW table and its guard:
--
--   * claimguard.run_explanations — one row per result record of a run,
--     recording HOW the reviewer-facing `explanation` text was produced:
--     which provider wrote it, whether the deterministic text stands
--     because a model path failed, and why a candidate was rejected.
--
-- Migration 0001 (the append-only hash-chained audit ledger and its single
-- canonical hash owner) and migration 0002 (rule_runs, rule_results,
-- review_decisions) are untouched.
--
-- WHY THIS IS A SIDECAR AND NOT A COLUMN OF rule_results
-- ------------------------------------------------------
-- The 15-key result record is the frozen pack contract
-- (schemas/result.schema.json, additionalProperties false) and the mentor
-- scorer rejects any extra or missing key. Provenance therefore sits BESIDE
-- the record — keyed by (run_id, rule_id), the same key rule_results uses —
-- and never inside it. The stored record keeps exactly its 15 keys; the
-- `explanation` it carries is the reviewer-facing text, and this table says
-- where that text came from.
--
-- WHY THE ROWS ARE IMMUTABLE
-- --------------------------
-- Provenance is evidence about what a reviewer was shown: which text a model
-- drafted and where the deterministic fallback stood in. Rewriting it after
-- the fact would make "this run showed model-assisted wording" as
-- unverifiable as a rewritten status, so UPDATE is refused exactly as it is
-- for rule_runs and rule_results. DELETE stays available to an operator
-- (retention/purge) and cascades from rule_runs, so a claim's history is
-- removed as one unit.
--
-- IDEMPOTENCY
-- -----------
-- Alembic records applied revisions, so a file runs once. Every statement is
-- still written to be re-runnable (IF NOT EXISTS / DROP TRIGGER IF EXISTS)
-- so that a half-applied development database can be repaired by re-running
-- the file.
-- =====================================================================

CREATE TABLE IF NOT EXISTS claimguard.run_explanations (
    -- One row per (run, rule): the run's 15 records each have exactly one
    -- provenance row, and `seq` pins the same R001..R015 order rule_results
    -- uses so a reader can line the two up without a join on rule_id.
    run_id            TEXT NOT NULL
                      REFERENCES claimguard.rule_runs (run_id) ON DELETE CASCADE,
    rule_id           TEXT NOT NULL CHECK (rule_id ~ '^R0(0[1-9]|1[0-5])$'),
    seq               INTEGER NOT NULL CHECK (seq BETWEEN 1 AND 15),
    -- 'deterministic' — the text shown was produced without a model (the
    -- template path or the engine's own explanation);
    -- 'model' — a model drafted the text and the verifier accepted it.
    source            TEXT NOT NULL CHECK (source IN ('deterministic','model')),
    -- The provider that produced the text ('template', 'model', 'none', ...).
    provider          TEXT NOT NULL CHECK (btrim(provider) <> ''),
    -- True when the record's explanation was replaced by this layer; false
    -- when the engine's own explanation is what the reviewer reads.
    rewritten         BOOLEAN NOT NULL,
    -- True when the deterministic text stands because the model path did not
    -- deliver (absent, failed, malformed or rejected).
    fallback_used     BOOLEAN NOT NULL,
    -- Why a candidate explanation was refused (the pack's citation contract,
    -- the layer's prohibitions). An array so the reviewer report can list
    -- every reason, not just the first.
    rejection_reasons JSONB NOT NULL DEFAULT '[]'::jsonb
                      CHECK (jsonb_typeof(rejection_reasons) = 'array'),
    -- Why the record was not rewritten at all (no citable evidence, or a
    -- status that is not sent to a model). NULL when it was rewritten.
    declined_reason   TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_run_explanations PRIMARY KEY (run_id, rule_id),
    CONSTRAINT uq_run_explanations_run_seq UNIQUE (run_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_run_explanations_run_id ON claimguard.run_explanations (run_id);

-- ---------------------------------------------------------------------
-- Immutability guard, reusing migration 0002's generic function so the
-- refusal message names the object that refused the write.
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_run_explanations_no_update ON claimguard.run_explanations;
CREATE TRIGGER trg_run_explanations_no_update
    BEFORE UPDATE ON claimguard.run_explanations
    FOR EACH ROW EXECUTE FUNCTION claimguard.review_no_modify();

-- ---------------------------------------------------------------------
-- Privileges, mirroring 0002 §Privileges: migration 0001's
-- `GRANT ... ON ALL TABLES IN SCHEMA claimguard` covers only the tables that
-- existed then, so the new table is granted explicitly. The DO block keeps
-- the file runnable where the role is absent.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claimguard_app') THEN
        EXECUTE 'GRANT SELECT, INSERT, DELETE ON claimguard.run_explanations TO claimguard_app';
    END IF;
END
$$;
