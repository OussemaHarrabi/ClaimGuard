-- revision = '0010'
-- down_revision = '0009'
--
-- Prevent cross-clinic run references even if a future caller forgets a
-- tenant predicate. The run table already has UNIQUE (tenant_id, run_id).
ALTER TABLE claimguard.clinic_requests
    ADD CONSTRAINT fk_clinic_requests_tenant_run
    FOREIGN KEY (tenant_id, run_id)
    REFERENCES claimguard.rule_runs (tenant_id, run_id);

ALTER TABLE claimguard.clinic_escalations
    ADD CONSTRAINT fk_clinic_escalations_tenant_run
    FOREIGN KEY (tenant_id, run_id)
    REFERENCES claimguard.rule_runs (tenant_id, run_id);

ALTER TABLE claimguard.intake_jobs
    ADD CONSTRAINT fk_intake_jobs_tenant_run
    FOREIGN KEY (tenant_id, run_id)
    REFERENCES claimguard.rule_runs (tenant_id, run_id);
