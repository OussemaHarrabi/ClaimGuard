-- revision = '0005'
-- down_revision = '0004'
--
-- Expand-only clinic identity directory. This migration deliberately does not
-- tenant-scope the existing review tables yet. The follow-on migration must
-- backfill and enforce tenant ownership before clinic authentication is enabled
-- on claim routes. The frozen 17-key input and 15-key result are untouched.

CREATE TABLE claimguard.clinics (
    tenant_id  TEXT PRIMARY KEY CHECK (btrim(tenant_id) <> ''),
    name       TEXT NOT NULL CHECK (btrim(name) <> ''),
    active     BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE claimguard.users (
    user_id      TEXT PRIMARY KEY CHECK (btrim(user_id) <> ''),
    email        TEXT NOT NULL UNIQUE CHECK (btrim(email) <> ''),
    display_name TEXT,
    active       BOOLEAN NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_users_email_casefold ON claimguard.users (lower(email));

CREATE TABLE claimguard.clinic_memberships (
    tenant_id  TEXT NOT NULL REFERENCES claimguard.clinics (tenant_id),
    user_id    TEXT NOT NULL REFERENCES claimguard.users (user_id),
    role       TEXT NOT NULL CHECK (
        role IN ('rcm_reviewer','rcm_lead','clinic_admin','technical_manager')
    ),
    active     BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);
CREATE INDEX ix_clinic_memberships_user ON claimguard.clinic_memberships (user_id);

CREATE TABLE claimguard.clinic_departments (
    department_id TEXT PRIMARY KEY CHECK (btrim(department_id) <> ''),
    tenant_id     TEXT NOT NULL REFERENCES claimguard.clinics (tenant_id),
    name          TEXT NOT NULL CHECK (btrim(name) <> ''),
    active        BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
CREATE INDEX ix_clinic_departments_tenant ON claimguard.clinic_departments (tenant_id);

-- The demo clinic is only a migration anchor for the upcoming review-table
-- backfill. It has no login and grants no access to existing claims.
INSERT INTO claimguard.clinics (tenant_id, name)
VALUES ('clinic-legacy-demo', 'Legacy synthetic demo');

GRANT SELECT ON claimguard.clinics, claimguard.users,
    claimguard.clinic_memberships, claimguard.clinic_departments TO claimguard_app;
