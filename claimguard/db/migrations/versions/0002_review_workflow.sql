-- =====================================================================
-- ClaimGuard — migration 0002: reviewer workflow
--
-- revision = '0002'
-- down_revision = '0001'
--
-- Alembic-managed raw-SQL migration (see claimguard/db/migrations/env.py,
-- which parses the two identifiers above, applies pending files in
-- dependency order inside one transaction and records them in
-- alembic_version).
--
-- SCOPE
-- -----
-- ADDITIVE ONLY. This migration creates three NEW tables and their
-- guards:
--
--   * claimguard.rule_runs       — one immutable engine run per claim version
--   * claimguard.rule_results    — that run's 15 frozen result records
--   * claimguard.review_decisions— append-only reviewer decisions
--
-- Nothing in migration 0001 is altered, dropped or rewritten: the
-- append-only hash-chained claimguard.audit_events ledger (and its single
-- canonical hash owner, claimguard.audit_chain_insert()) stays exactly as it
-- is and remains the audit authority. The review workflow APPENDS to it; see
-- claimguard/review/audit_events.py.
--
-- IDEMPOTENCY
-- -----------
-- Alembic records applied revisions, so a file runs once. Every statement is
-- still written to be re-runnable (IF NOT EXISTS / DROP TRIGGER IF EXISTS /
-- CREATE OR REPLACE) so that a half-applied development database can be
-- repaired by re-running the file, and so `alembic upgrade head` after a
-- manual partial apply cannot fail on a duplicate object.
--
-- WHY THESE GUARDS EXIST
-- ----------------------
--   * rule_runs is UPDATE-proof: a run row is the evidence that a given claim
--     version was checked with given rule/model/prompt versions. A correction
--     is a NEW run (new version, supersedes_run_id set), never an edit of the
--     old one (docs/07_Evaluation_and_Acceptance.md, non-negotiable checks).
--     DELETE stays available to an operator for retention/purge; the row is
--     immutable while it exists.
--   * rule_results is UPDATE-proof for the same reason: those 15 records are
--     the engine's frozen output and the scorer's input. A reviewer's status
--     never rewrites them — review state lives in review_decisions, derived on
--     read (claimguard/review/store.py).
--   * review_decisions is APPEND-ONLY (UPDATE and DELETE both refused): the
--     pack requires every human action to be recorded, and a rewritten history
--     is not a record. Two rows about the same finding are a legitimate
--     sequence (ask, then confirm), so appends are unrestricted.
-- =====================================================================

-- =====================================================================
-- 1. rule_runs — one immutable engine run over one claim version
-- =====================================================================
-- run_id       opaque run reference; also the claim_ref written to
--              audit_events for this run (never the visible claim id, which
--              lives in its own column and must not leak into the ledger).
-- version      claim version, 1-based; a correction inserts version + 1.
-- input_hash   sha256 of the canonical rendering of the submitted envelope:
--              re-running the same bytes must be recognisable as the same
--              input (dedupe), and a recheck must be a real change.
-- envelope     the submitted 17-key envelope, byte-faithful, so every
--              evidence pointer stays replayable against the original.
-- trace_id     32-hex correlation id shared with this run's audit events.
-- initiated_by who asked for the run: the submission surface, or the reviewer
--              who requested a recheck (recorded because a correction is a
--              human action). It is also carried in the run's audit event.
CREATE TABLE IF NOT EXISTS claimguard.rule_runs (
    run_id            TEXT PRIMARY KEY,
    claim_id          TEXT NOT NULL,
    version           INTEGER NOT NULL CHECK (version >= 1),
    supersedes_run_id TEXT REFERENCES claimguard.rule_runs (run_id) ON DELETE SET NULL,
    input_hash        TEXT NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    envelope          JSONB NOT NULL,
    trace_id          TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    rule_version      TEXT NOT NULL,
    model_version     TEXT NOT NULL,
    prompt_version    TEXT NOT NULL,
    initiated_by      TEXT NOT NULL CHECK (btrim(initiated_by) <> ''),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_rule_runs_claim_version UNIQUE (claim_id, version),
    -- A first version cannot supersede anything: supersedes_run_id is only
    -- meaningful for a correction (version >= 2).
    CONSTRAINT ck_rule_runs_supersedes CHECK (
        supersedes_run_id IS NULL OR (version >= 2 AND supersedes_run_id <> run_id)
    )
);
CREATE INDEX IF NOT EXISTS ix_rule_runs_claim_id ON claimguard.rule_runs (claim_id);
CREATE INDEX IF NOT EXISTS ix_rule_runs_supersedes ON claimguard.rule_runs (supersedes_run_id);

-- =====================================================================
-- 2. rule_results — the run's 15 frozen records (R001..R015)
-- =====================================================================
-- Columns mirror schemas/result.schema.json one-for-one; the CHECK
-- constraints restate the contract so a bad row cannot be stored even if the
-- application model is bypassed. `seq` pins the R001..R015 order.
CREATE TABLE IF NOT EXISTS claimguard.rule_results (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                TEXT NOT NULL REFERENCES claimguard.rule_runs (run_id) ON DELETE CASCADE,
    claim_id              TEXT NOT NULL,
    seq                   INTEGER NOT NULL CHECK (seq BETWEEN 1 AND 15),
    rule_id               TEXT NOT NULL CHECK (rule_id ~ '^R0(0[1-9]|1[0-5])$'),
    rule_version          TEXT NOT NULL,
    status                TEXT NOT NULL
                          CHECK (status IN ('PASS','FAIL','UNABLE_TO_ASSESS',
                                            'NOT_APPLICABLE','NOT_IMPLEMENTED')),
    severity              TEXT NOT NULL CHECK (severity IN ('high','medium','low')),
    affected_line_ids     TEXT[] NOT NULL DEFAULT '{}',
    evidence              JSONB NOT NULL,
    rule_source           TEXT NOT NULL,
    explanation           TEXT NOT NULL,
    corrective_action     TEXT NOT NULL,
    confidence            NUMERIC,
    confidence_kind       TEXT NOT NULL
                          CHECK (confidence_kind IN ('not_probabilistic','uncalibrated',
                                                     'calibrated')),
    requires_human_review BOOLEAN NOT NULL,
    method                TEXT NOT NULL CHECK (method IN ('deterministic','hybrid','llm')),
    review_status         TEXT NOT NULL DEFAULT 'unreviewed'
                          CHECK (review_status IN ('unreviewed','reviewed')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_rule_results_run_rule UNIQUE (run_id, rule_id),
    CONSTRAINT uq_rule_results_run_seq UNIQUE (run_id, seq),
    -- Deterministic checks are not probabilistic: confidence must stay null
    -- wherever the record declares not_probabilistic (schemas/result.schema.json).
    CONSTRAINT ck_rule_results_confidence CHECK (
        confidence_kind <> 'not_probabilistic' OR confidence IS NULL
    )
);
CREATE INDEX IF NOT EXISTS ix_rule_results_claim_id ON claimguard.rule_results (claim_id);
CREATE INDEX IF NOT EXISTS ix_rule_results_rule_id ON claimguard.rule_results (rule_id);
CREATE INDEX IF NOT EXISTS ix_rule_results_status ON claimguard.rule_results (status);
CREATE INDEX IF NOT EXISTS ix_rule_results_severity ON claimguard.rule_results (severity);

-- =====================================================================
-- 3. review_decisions — APPEND-ONLY reviewer decisions
-- =====================================================================
-- The seven columns claim_id..original_status are the pack's review_event
-- contract (schemas/review_event.schema.json, additionalProperties false);
-- decision_id / run_id / seq are this table's own identifiers. `seq` gives a
-- total order for deriving "the current status" without depending on
-- timestamp resolution, and `run_id` binds the decision to the exact claim
-- version it reviewed (the pack keys on claim_id + rule_id, which would
-- otherwise collide across versions of the same claim).
--
-- original_status is the RULE status of the finding at decision time
-- (FAIL / UNABLE_TO_ASSESS / ...); see the module docstring of
-- claimguard/review/models.py for why the pack's own review page settles it.
-- `reason` is free text by design (the pack requires a reason), and the store
-- additionally requires a non-blank one.
CREATE TABLE IF NOT EXISTS claimguard.review_decisions (
    decision_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seq             BIGSERIAL NOT NULL UNIQUE,
    run_id          TEXT NOT NULL REFERENCES claimguard.rule_runs (run_id) ON DELETE CASCADE,
    claim_id        TEXT NOT NULL,
    rule_id         TEXT NOT NULL,
    action          TEXT NOT NULL
                    CHECK (action IN ('confirm_issue','dismiss_with_reason',
                                      'request_information','mark_corrected_for_recheck')),
    actor           TEXT NOT NULL CHECK (btrim(actor) <> ''),
    reason          TEXT NOT NULL CHECK (btrim(reason) <> ''),
    original_status TEXT NOT NULL
                    CHECK (original_status IN ('PASS','FAIL','UNABLE_TO_ASSESS',
                                               'NOT_APPLICABLE','NOT_IMPLEMENTED')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_review_decisions_run_id ON claimguard.review_decisions (run_id);
CREATE INDEX IF NOT EXISTS ix_review_decisions_claim_rule
    ON claimguard.review_decisions (claim_id, rule_id);
CREATE INDEX IF NOT EXISTS ix_review_decisions_created_at ON claimguard.review_decisions (created_at);

-- ---------------------------------------------------------------------
-- Immutability guards.
--
-- One generic trigger function, keyed by TG_TABLE_NAME/TG_OP, so the message
-- names the object that refused the write. These are defence in depth: the
-- application never issues UPDATE/DELETE against these tables, and the
-- database refuses it anyway (including for the table owner — only a
-- deliberate DISABLE TRIGGER, as used by the test cleanup, gets around it).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION claimguard.review_no_modify() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'claimguard.% is immutable here: % is refused (a correction is a new run)',
        TG_TABLE_NAME, TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS trg_rule_runs_no_update ON claimguard.rule_runs;
CREATE TRIGGER trg_rule_runs_no_update
    BEFORE UPDATE ON claimguard.rule_runs
    FOR EACH ROW EXECUTE FUNCTION claimguard.review_no_modify();

DROP TRIGGER IF EXISTS trg_rule_results_no_update ON claimguard.rule_results;
CREATE TRIGGER trg_rule_results_no_update
    BEFORE UPDATE ON claimguard.rule_results
    FOR EACH ROW EXECUTE FUNCTION claimguard.review_no_modify();

DROP TRIGGER IF EXISTS trg_review_decisions_no_modify ON claimguard.review_decisions;
CREATE TRIGGER trg_review_decisions_no_modify
    BEFORE UPDATE OR DELETE ON claimguard.review_decisions
    FOR EACH ROW EXECUTE FUNCTION claimguard.review_no_modify();

-- ---------------------------------------------------------------------
-- Privileges, mirroring 0001 §15.
--
-- Migration 0001's `GRANT ... ON ALL TABLES IN SCHEMA claimguard` covers only
-- the tables that existed then, so the new tables are granted explicitly.
-- review_decisions is append-only for the application role, exactly like
-- audit_events. The DO block keeps the file runnable where the role is
-- absent (a bare database restored from a partial state): GRANT cannot be
-- written as a plpgsql statement, hence EXECUTE.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claimguard_app') THEN
        EXECUTE 'GRANT SELECT, INSERT, DELETE ON claimguard.rule_runs TO claimguard_app';
        EXECUTE 'GRANT SELECT, INSERT, DELETE ON claimguard.rule_results TO claimguard_app';
        EXECUTE 'GRANT SELECT, INSERT ON claimguard.review_decisions TO claimguard_app';
        EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES '
                'ON claimguard.review_decisions FROM claimguard_app';
        EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE claimguard.review_decisions_seq_seq '
                'TO claimguard_app';
    END IF;
END
$$;
