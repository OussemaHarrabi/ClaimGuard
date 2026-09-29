-- revision = '0009'
-- down_revision = '0008'
--
-- Human review collaboration and a bounded synthetic-document intake pilot.
-- Raw document text is never stored: only a validated JSON draft and hash.
CREATE TABLE claimguard.clinic_requests (
    request_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES claimguard.clinics (tenant_id),
    run_id TEXT NOT NULL REFERENCES claimguard.rule_runs (run_id),
    message TEXT NOT NULL,
    response TEXT,
    status TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
    created_by TEXT NOT NULL REFERENCES claimguard.users (user_id),
    resolved_by TEXT REFERENCES claimguard.users (user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);
CREATE INDEX ix_clinic_requests_tenant_created ON claimguard.clinic_requests (tenant_id, created_at DESC);

CREATE TABLE claimguard.clinic_escalations (
    escalation_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES claimguard.clinics (tenant_id),
    run_id TEXT NOT NULL REFERENCES claimguard.rule_runs (run_id),
    reason TEXT NOT NULL,
    resolution TEXT,
    status TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
    created_by TEXT NOT NULL REFERENCES claimguard.users (user_id),
    resolved_by TEXT REFERENCES claimguard.users (user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);
CREATE INDEX ix_clinic_escalations_tenant_created ON claimguard.clinic_escalations (tenant_id, created_at DESC);

CREATE TABLE claimguard.intake_jobs (
    job_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES claimguard.clinics (tenant_id),
    submitted_by TEXT NOT NULL REFERENCES claimguard.users (user_id),
    filename TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    draft JSONB,
    status TEXT NOT NULL CHECK (status IN ('needs_review', 'rejected', 'submitted')),
    error_code TEXT,
    run_id TEXT REFERENCES claimguard.rule_runs (run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_intake_jobs_tenant_created ON claimguard.intake_jobs (tenant_id, created_at DESC);

CREATE TABLE claimguard.clinic_configuration (
    tenant_id TEXT PRIMARY KEY REFERENCES claimguard.clinics (tenant_id),
    intake_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by TEXT REFERENCES claimguard.users (user_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON claimguard.clinic_requests TO claimguard_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON claimguard.clinic_escalations TO claimguard_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON claimguard.intake_jobs TO claimguard_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON claimguard.clinic_configuration TO claimguard_app;
