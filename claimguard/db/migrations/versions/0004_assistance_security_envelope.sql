-- revision = '0004'
-- down_revision = '0003'
--
-- Add the AegisGraph-inspired assistance envelope beside the frozen result
-- contract. Existing rows remain explicitly legacy/unrecorded; new rows carry
-- the SLM correction recommendation, its evidence citations, the fail-closed
-- decision, and the exact SHA-256 receipt shown to the reviewer.

ALTER TABLE claimguard.run_explanations
    ADD COLUMN IF NOT EXISTS correction_recommendation TEXT NOT NULL
        DEFAULT 'No SLM correction recommendation was recorded for this legacy run.',
    ADD COLUMN IF NOT EXISTS cited_evidence_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS security_decision TEXT NOT NULL DEFAULT 'unrecorded',
    ADD COLUMN IF NOT EXISTS receipt_sha256 TEXT;

ALTER TABLE claimguard.run_explanations
    DROP CONSTRAINT IF EXISTS ck_run_explanations_cited_evidence_paths,
    ADD CONSTRAINT ck_run_explanations_cited_evidence_paths
        CHECK (jsonb_typeof(cited_evidence_paths) = 'array'),
    DROP CONSTRAINT IF EXISTS ck_run_explanations_security_decision,
    ADD CONSTRAINT ck_run_explanations_security_decision
        CHECK (security_decision IN ('accept','fallback','decline','unrecorded')),
    DROP CONSTRAINT IF EXISTS ck_run_explanations_receipt_sha256,
    ADD CONSTRAINT ck_run_explanations_receipt_sha256
        CHECK (receipt_sha256 IS NULL OR receipt_sha256 ~ '^[0-9a-f]{64}$');

ALTER TABLE claimguard.run_explanations
    ALTER COLUMN correction_recommendation DROP DEFAULT,
    ALTER COLUMN cited_evidence_paths DROP DEFAULT,
    ALTER COLUMN security_decision DROP DEFAULT;
