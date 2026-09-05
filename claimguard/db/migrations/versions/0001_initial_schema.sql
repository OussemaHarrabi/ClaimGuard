-- =====================================================================
-- ClaimGuard — migration 0001: initial schema
--
-- revision = '0001'
-- down_revision = None
--
-- Alembic-managed raw-SQL migration. Alembic discovers revisions only as
-- Python modules, so claimguard/db/migrations/env.py reads these header
-- identifiers, applies pending files in dependency order inside one
-- transaction and records them in alembic_version.
--
-- HASH-SERIALISATION CONTRACT (P0-3 — see docs/09 §Part B): the trigger
-- claimguard.audit_chain_insert() defined below is the SINGLE CANONICAL
-- OWNER of the audit hash serialisation. The Python replica lives in
-- claimguard/audit/chain.py and MUST match this trigger character-for-
-- character — same fields, same order, no separator, same NULL coercion,
-- same list join. ANY change on either side MUST be mirrored on the other
-- (and in claimguard.verify_audit_chain() below).
-- =====================================================================

CREATE SCHEMA claimguard;

-- =====================================================================
-- 1. claim_packages — the raw synthetic claim package, byte-faithful
--    (FHIR R4 JSON and/or CSV; synthetic data only)
-- =====================================================================
CREATE TABLE claimguard.claim_packages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id        TEXT NOT NULL,              -- visible id, e.g. 'CLM-0042'
    raw_json        JSONB NOT NULL,             -- raw package, encrypted at rest by the app layer
    input_hash      TEXT NOT NULL,              -- sha256 of the raw bytes (dedupe / integrity)
    envelope_ok     BOOLEAN NOT NULL DEFAULT false,
    envelope_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    status          TEXT NOT NULL DEFAULT 'received'
                    CHECK (status IN ('received','normalized','validated','handoff','failed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_claim_packages_claim_id ON claimguard.claim_packages (claim_id);

-- =====================================================================
-- 2. canonical_claims — the normalized shape (one per accepted package)
-- =====================================================================
CREATE TABLE claimguard.canonical_claims (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    package_id UUID NOT NULL UNIQUE REFERENCES claimguard.claim_packages (id) ON DELETE CASCADE,
    claim_id   TEXT NOT NULL,                    -- visible id, e.g. 'CLM-0042'
    payload    JSONB NOT NULL,                   -- canonical claim (Pydantic model_dump)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_canonical_claims_claim_id ON claimguard.canonical_claims (claim_id);

-- =====================================================================
-- 3. findings — one concrete detected problem per rule firing
-- =====================================================================
CREATE TABLE claimguard.findings (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id             TEXT NOT NULL,
    rule_id              TEXT NOT NULL,
    rule_version         INTEGER NOT NULL,
    family               TEXT NOT NULL,          -- Coverage|Authorization|Integrity|Identity|Documentation|Clean
    severity             TEXT NOT NULL CHECK (severity IN ('info','minor','major','critical')),
    tone                 TEXT NOT NULL CHECK (tone IN ('red','amber')),
    confidence           NUMERIC,                -- informational for deterministic rules (docs/05 §7.4)
    title                TEXT NOT NULL,
    detail               TEXT NOT NULL,
    suggested_action     TEXT,
    mandatory_escalation BOOLEAN NOT NULL DEFAULT false,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_findings_claim_id ON claimguard.findings (claim_id);
CREATE INDEX ix_findings_rule_id ON claimguard.findings (rule_id);

-- =====================================================================
-- 4. finding_evidence — every evidence item cited by a finding
-- =====================================================================
CREATE TABLE claimguard.finding_evidence (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id     UUID NOT NULL REFERENCES claimguard.findings (id) ON DELETE CASCADE,
    json_pointer   TEXT NOT NULL,                -- RFC 6901 pointer into raw_json / payload
    rule_id        TEXT NOT NULL,
    value_snapshot TEXT,                         -- quoted value at the pointer (never raw PHI blobs)
    derived        BOOLEAN NOT NULL DEFAULT false
);

-- =====================================================================
-- 5. audit_events — APPEND-ONLY, hash-chained event ledger
-- =====================================================================
-- Chain order is (at, event_id), used identically by the insert trigger, by
-- claimguard.verify_audit_chain() and by the Python replica. `at` defaults to
-- the transaction timestamp, so when inserting several events in one
-- transaction either pass explicit distinct timestamps or accept that equal
-- `at` values are tie-broken by event_id (deterministic on both sides).
--
-- NOTE: `at::text` renders in the session TimeZone; application connections
-- MUST run with TimeZone=UTC so Python-side replication agrees bit-for-bit.
CREATE TABLE claimguard.audit_events (
    event_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind         TEXT NOT NULL
                 CHECK (kind IN ('claim_received','normalized','validated','finding_created',
                                 'finding.suppressed','escalated','review_decided','override_applied',
                                 'rule_published','benchmark_run','llm_called','handoff')),
    claim_ref    TEXT,                           -- opaque reference; never the visible claim id
    trace_id     TEXT NOT NULL,                  -- OpenTelemetry trace id (per-claim trace)
    decision     TEXT,
    reason_code  TEXT,
    finding_ids  TEXT[] NOT NULL DEFAULT '{}',
    rule_version TEXT,
    model_version TEXT,
    prev_hash    TEXT NOT NULL,                  -- set by trg_audit_chain ('genesis' for the first event)
    chain_hash   TEXT NOT NULL                   -- set by trg_audit_chain (sha256 hex)
);
CREATE INDEX ix_audit_at ON claimguard.audit_events (at);
CREATE INDEX ix_audit_trace_id ON claimguard.audit_events (trace_id);
CREATE INDEX ix_audit_claim_ref ON claimguard.audit_events (claim_ref);

-- =====================================================================
-- 15. roles, privileges and the append-only audit  (docs/05 §15)
-- =====================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claimguard_app') THEN
        CREATE ROLE claimguard_app NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA claimguard TO claimguard_app;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA claimguard TO claimguard_app;

-- audit_events is APPEND-ONLY for the application role:
REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES ON claimguard.audit_events FROM claimguard_app;

-- Defense in depth: even a privileged/buggy connection cannot mutate rows
-- (the trigger fires for the table owner too; TRUNCATE is additionally
-- revoked above, though superusers keep that right by design).
CREATE OR REPLACE FUNCTION claimguard.audit_no_modify() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: event % cannot be updated or deleted',
        OLD.event_id::text;
END;
$$;

CREATE TRIGGER trg_audit_no_modify
    BEFORE UPDATE OR DELETE ON claimguard.audit_events
    FOR EACH ROW EXECUTE FUNCTION claimguard.audit_no_modify();

-- ---------------------------------------------------------------------
-- Hash chain insert trigger — THE CANONICAL OWNER of the serialisation.
-- sha256 over: prev_hash || at::text || COALESCE(claim_ref::text,'') ||
-- trace_id || COALESCE(decision,'') || COALESCE(reason_code,'') ||
-- COALESCE(array_to_string(finding_ids, ','),'') || COALESCE(model_version,'')
-- (fields in this order, NO separator, NULL -> ''), UTF-8, lowercase hex.
-- Mirror in claimguard/audit/chain.py (P0-3).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION claimguard.audit_chain_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_prev TEXT;
BEGIN
    SELECT chain_hash INTO v_prev
      FROM claimguard.audit_events
     ORDER BY at DESC, event_id DESC
     LIMIT 1;
    NEW.prev_hash := COALESCE(v_prev, 'genesis');
    NEW.chain_hash := encode(
        sha256(
            convert_to(
                NEW.prev_hash || NEW.at::text ||
                COALESCE(NEW.claim_ref::text, '') || NEW.trace_id ||
                COALESCE(NEW.decision, '') || COALESCE(NEW.reason_code, '') ||
                COALESCE(array_to_string(NEW.finding_ids, ','), '') ||
                COALESCE(NEW.model_version, ''),
                'UTF8'
            )
        ),
        'hex'
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_audit_chain
    BEFORE INSERT ON claimguard.audit_events
    FOR EACH ROW EXECUTE FUNCTION claimguard.audit_chain_insert();

-- ---------------------------------------------------------------------
-- Chain verifier: walks the chain in (at, event_id) order and returns one
-- row per broken link (bad prev_hash link or stored chain_hash not matching
-- a fresh recomputation of the event's own fields). Exposed as
-- GET /v1/audit/verify and run by the nightly integrity job.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION claimguard.verify_audit_chain()
RETURNS TABLE (broken_at TIMESTAMPTZ, event_id UUID, expected TEXT, stored TEXT)
LANGUAGE plpgsql AS $$
DECLARE
    v_prev             TEXT := 'genesis';
    v_expected_prev    TEXT;
    v_expected_hash    TEXT;
    r                  RECORD;
BEGIN
    FOR r IN
        SELECT * FROM claimguard.audit_events
        ORDER BY at ASC, event_id ASC
    LOOP
        v_expected_prev := v_prev;
        v_expected_hash := encode(
            sha256(
                convert_to(
                    r.prev_hash || r.at::text ||
                    COALESCE(r.claim_ref::text, '') || r.trace_id ||
                    COALESCE(r.decision, '') || COALESCE(r.reason_code, '') ||
                    COALESCE(array_to_string(r.finding_ids, ','), '') ||
                    COALESCE(r.model_version, ''),
                    'UTF8'
                )
            ),
            'hex'
        );
        IF r.prev_hash IS DISTINCT FROM v_expected_prev THEN
            broken_at := r.at;
            event_id  := r.event_id;
            expected  := 'prev_hash=' || v_expected_prev;
            stored    := r.prev_hash;
            RETURN NEXT;
        ELSIF r.chain_hash IS DISTINCT FROM v_expected_hash THEN
            broken_at := r.at;
            event_id  := r.event_id;
            expected  := 'chain_hash=' || v_expected_hash;
            stored    := r.chain_hash;
            RETURN NEXT;
        END IF;
        v_prev := r.chain_hash;
    END LOOP;
END;
$$;