-- revision = '0008'
-- down_revision = '0007'
--
-- One current reviewer assignment per clinic-scoped claim identity. Assignments
-- survive immutable recheck versions and are changed only by an authorized lead
-- or clinic admin through the clinic API.
CREATE TABLE claimguard.claim_assignments (
    tenant_id TEXT NOT NULL REFERENCES claimguard.clinics (tenant_id),
    claim_id TEXT NOT NULL,
    reviewer_user_id TEXT NOT NULL REFERENCES claimguard.users (user_id),
    assigned_by TEXT NOT NULL REFERENCES claimguard.users (user_id),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, claim_id)
);
CREATE INDEX ix_claim_assignments_reviewer
    ON claimguard.claim_assignments (tenant_id, reviewer_user_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON claimguard.claim_assignments TO claimguard_app;
