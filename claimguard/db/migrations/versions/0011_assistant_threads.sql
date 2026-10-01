-- =====================================================================
-- ClaimGuard — migration 0011: interactive assistant threads
--
-- revision = '0011'
-- down_revision = '0010'
--
-- Alembic-managed raw-SQL migration (see claimguard/db/migrations/env.py,
-- which parses the two identifiers above, applies pending files in
-- dependency order inside one transaction and records them in
-- alembic_version).
--
-- SCOPE
-- -----
-- ADDITIVE ONLY. Two NEW tables, and nothing else is touched:
--
--   * claimguard.assistant_threads — one conversation per reviewer, per
--     finding. A finding is identified the way the rest of the schema
--     identifies it: (run_id, rule_id).
--   * claimguard.assistant_turns — the conversation itself: the reviewer's
--     question and the assistant's answer, with the provenance of how that
--     answer was produced and verified.
--
-- WHY THIS IS A SIDECAR AND NOT PART OF THE RESULT RECORD
-- -------------------------------------------------------
-- The 15-key result record is the frozen pack contract and the mentor's
-- scorer rejects any extra or missing key. The assistant therefore never
-- writes to rule_results, run_explanations or audit_events: it READS a stored
-- run and stores its own conversation beside it. Its answer carries the same
-- five keys the graded explanation layer produces
-- (claimguard/edu/explain/verifier.py, EXPLANATION_KEYS) so one reviewer
-- contract serves both surfaces — but where that text lives is this table,
-- not the record. A conversation can never change a status, a severity or an
-- evidence pointer.
--
-- WHY THE TURNS ARE IMMUTABLE
-- ---------------------------
-- A turn is evidence of what a reviewer was told: which question they asked,
-- which model answered, whether the verifier accepted it, and what stood in
-- when it did not. Rewriting that after the fact would make "this reviewer was
-- shown a verified answer" as unverifiable as a rewritten status. UPDATE is
-- therefore refused, exactly as it is for rule_runs and run_explanations.
-- DELETE stays available to an operator and cascades from the thread (and the
-- thread cascades from the run), so a claim's conversation is removed as one
-- unit rather than orphaned.
--
-- WHY THE THREAD IS NOT IMMUTABLE
-- -------------------------------
-- A thread may be closed (closed_at) so the interface can stop offering a
-- conversation that is finished. That is a lifecycle fact, not evidence about
-- an answer, and it is the only column that is expected to change.
--
-- IDEMPOTENCY
-- -----------
-- Alembic records applied revisions, so a file runs once. Every statement is
-- still written to be re-runnable (IF NOT EXISTS / DROP TRIGGER IF EXISTS).
-- =====================================================================

CREATE TABLE IF NOT EXISTS claimguard.assistant_threads (
    thread_id   UUID NOT NULL DEFAULT gen_random_uuid(),
    -- The tenant owns the conversation; the API resolves it from the session
    -- and never from the request body.
    tenant_id   TEXT NOT NULL CHECK (btrim(tenant_id) <> ''),
    run_id      TEXT NOT NULL
                REFERENCES claimguard.rule_runs (run_id) ON DELETE CASCADE,
    -- Kept beside run_id because the conversation is about a claim first: the
    -- queue and the audit report both address it that way, and denormalising
    -- it avoids a join on every listing.
    claim_id    TEXT NOT NULL CHECK (btrim(claim_id) <> ''),
    rule_id     TEXT NOT NULL CHECK (rule_id ~ '^R0(0[1-9]|1[0-5])$'),
    -- The reviewer who opened it. A conversation is personal: the unique
    -- constraint below keys on this, so one reviewer's thread never shows up
    -- inside another's.
    created_by  TEXT NOT NULL CHECK (btrim(created_by) <> ''),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at   TIMESTAMPTZ,
    CONSTRAINT pk_assistant_threads PRIMARY KEY (thread_id),
    CONSTRAINT uq_assistant_threads_owner
        UNIQUE (tenant_id, run_id, rule_id, created_by)
);
CREATE INDEX IF NOT EXISTS ix_assistant_threads_run
    ON claimguard.assistant_threads (tenant_id, run_id, rule_id);

CREATE TABLE IF NOT EXISTS claimguard.assistant_turns (
    turn_id     UUID NOT NULL DEFAULT gen_random_uuid(),
    thread_id   UUID NOT NULL
                REFERENCES claimguard.assistant_threads (thread_id) ON DELETE CASCADE,
    tenant_id   TEXT NOT NULL CHECK (btrim(tenant_id) <> ''),
    -- 1-based position in the conversation. The pair is unique so two turns
    -- can never claim the same place, and a reader can replay the thread in
    -- order without trusting created_at.
    seq         INTEGER NOT NULL CHECK (seq > 0),
    role        TEXT NOT NULL CHECK (role IN ('reviewer', 'assistant')),
    -- The reviewer's question. NULL for the opening assistant turn, which
    -- answers the interface's own "why is this flagged?" rather than a typed
    -- question.
    question    TEXT,
    -- The assistant's answer: the five validated keys, or NULL on a reviewer
    -- turn, or an object carrying the refusal/fallback text when no model
    -- answer was accepted. The type is asserted so a malformed row cannot be
    -- read as a valid answer.
    answer      JSONB CHECK (answer IS NULL OR jsonb_typeof(answer) = 'object'),
    -- How much of the answer a model actually wrote:
    --   'accepted' — a model drafted it and the verifier passed it unchanged;
    --   'repaired' — drafted, rejected once, and accepted after one bounded
    --                retry that was given the rejection reasons;
    --   'fallback' — no model text was served; the deterministic explanation
    --                stands and this column says so;
    --   'refused'  — the turn is a refusal (out of scope, rate-limited, or a
    --                question about something this finding cannot support).
    verification TEXT NOT NULL
                 CHECK (verification IN ('accepted', 'repaired', 'fallback', 'refused')),
    -- Every reason a candidate answer was not served, so the interface can
    -- show why rather than silently degrading.
    reasons     JSONB NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(reasons) = 'array'),
    -- Which model and prompt produced this turn. Both are recorded even when
    -- the answer fell back, because "we asked and it was refused" is the fact
    -- an auditor needs.
    model_version  TEXT NOT NULL DEFAULT 'none' CHECK (btrim(model_version) <> ''),
    prompt_version TEXT NOT NULL DEFAULT 'none' CHECK (btrim(prompt_version) <> ''),
    -- SHA-256 over this turn's own fields, so a reader can tell a re-served
    -- answer from one that was edited in place. NULL for reviewer turns.
    receipt     TEXT CHECK (receipt IS NULL OR receipt ~ '^[0-9a-f]{64}$'),
    latency_ms  INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_assistant_turns PRIMARY KEY (turn_id),
    CONSTRAINT uq_assistant_turns_seq UNIQUE (thread_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_assistant_turns_thread
    ON claimguard.assistant_turns (thread_id, seq);

-- ---------------------------------------------------------------------
-- Immutability guard for the turns, reusing migration 0002's generic
-- function so the refusal message names the object that refused the write.
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_assistant_turns_no_update ON claimguard.assistant_turns;
CREATE TRIGGER trg_assistant_turns_no_update
    BEFORE UPDATE ON claimguard.assistant_turns
    FOR EACH ROW EXECUTE FUNCTION claimguard.review_no_modify();

-- ---------------------------------------------------------------------
-- Privileges, mirroring 0002 §Privileges: migration 0001's
-- `GRANT ... ON ALL TABLES IN SCHEMA claimguard` covers only the tables that
-- existed then, so the new tables are granted explicitly. The DO block keeps
-- the file runnable where the role is absent.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claimguard_app') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON claimguard.assistant_threads TO claimguard_app';
        EXECUTE 'GRANT SELECT, INSERT, DELETE ON claimguard.assistant_turns TO claimguard_app';
    END IF;
END
$$;
