-- revision = '0006'
-- down_revision = '0005'
--
-- Assign all historical synthetic review rows to the legacy demo clinic.
-- The 17-key input, 15-key result, and append-only audit ledger are unchanged.

ALTER TABLE claimguard.rule_runs ADD COLUMN tenant_id TEXT
    REFERENCES claimguard.clinics (tenant_id);
ALTER TABLE claimguard.rule_results ADD COLUMN tenant_id TEXT;
ALTER TABLE claimguard.review_decisions ADD COLUMN tenant_id TEXT;
ALTER TABLE claimguard.run_explanations ADD COLUMN tenant_id TEXT;

-- Existing review rows are immutable in normal operation. Temporarily stand
-- down only their UPDATE guards for the one-time ownership backfill.
ALTER TABLE claimguard.rule_runs DISABLE TRIGGER trg_rule_runs_no_update;
ALTER TABLE claimguard.rule_results DISABLE TRIGGER trg_rule_results_no_update;
ALTER TABLE claimguard.review_decisions DISABLE TRIGGER trg_review_decisions_no_modify;
ALTER TABLE claimguard.run_explanations DISABLE TRIGGER trg_run_explanations_no_update;

UPDATE claimguard.rule_runs SET tenant_id = 'clinic-legacy-demo';
UPDATE claimguard.rule_results AS result
SET tenant_id = run.tenant_id
FROM claimguard.rule_runs AS run WHERE run.run_id = result.run_id;
UPDATE claimguard.review_decisions AS decision
SET tenant_id = run.tenant_id
FROM claimguard.rule_runs AS run WHERE run.run_id = decision.run_id;
UPDATE claimguard.run_explanations AS explanation
SET tenant_id = run.tenant_id
FROM claimguard.rule_runs AS run WHERE run.run_id = explanation.run_id;

ALTER TABLE claimguard.rule_runs ENABLE TRIGGER trg_rule_runs_no_update;
ALTER TABLE claimguard.rule_results ENABLE TRIGGER trg_rule_results_no_update;
ALTER TABLE claimguard.review_decisions ENABLE TRIGGER trg_review_decisions_no_modify;
ALTER TABLE claimguard.run_explanations ENABLE TRIGGER trg_run_explanations_no_update;

ALTER TABLE claimguard.rule_runs ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE claimguard.rule_results ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE claimguard.review_decisions ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE claimguard.run_explanations ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE claimguard.rule_runs DROP CONSTRAINT uq_rule_runs_claim_version;
ALTER TABLE claimguard.rule_runs ADD CONSTRAINT uq_rule_runs_tenant_claim_version
    UNIQUE (tenant_id, claim_id, version);
ALTER TABLE claimguard.rule_runs ADD CONSTRAINT uq_rule_runs_tenant_run
    UNIQUE (tenant_id, run_id);
CREATE INDEX ix_rule_runs_tenant_created ON claimguard.rule_runs (tenant_id, created_at DESC);

ALTER TABLE claimguard.rule_results ADD CONSTRAINT fk_rule_results_tenant_run
    FOREIGN KEY (tenant_id, run_id)
    REFERENCES claimguard.rule_runs (tenant_id, run_id) ON DELETE CASCADE;
ALTER TABLE claimguard.review_decisions ADD CONSTRAINT fk_review_decisions_tenant_run
    FOREIGN KEY (tenant_id, run_id)
    REFERENCES claimguard.rule_runs (tenant_id, run_id) ON DELETE CASCADE;
ALTER TABLE claimguard.run_explanations ADD CONSTRAINT fk_run_explanations_tenant_run
    FOREIGN KEY (tenant_id, run_id)
    REFERENCES claimguard.rule_runs (tenant_id, run_id) ON DELETE CASCADE;

CREATE INDEX ix_rule_results_tenant_run ON claimguard.rule_results (tenant_id, run_id);
CREATE INDEX ix_review_decisions_tenant_run ON claimguard.review_decisions (tenant_id, run_id);
CREATE INDEX ix_run_explanations_tenant_run ON claimguard.run_explanations (tenant_id, run_id);
