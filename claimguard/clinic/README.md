# Clinic platform, identity, and tenancy

`claimguard.clinic` implements the clinic directory, local credentials, signed sessions, role-based authorization, departments, assignments, workspace read models, and multi-format intake jobs.

[Back to the project README](../../README.md)

## Tenant model

One clinic is one tenant. A global user record is connected to a clinic through `clinic_memberships`, which assigns a role. Clinic-owned records carry `tenant_id`, and tenant-qualified foreign keys prevent several classes of cross-clinic relationship mistakes.

The API derives the active tenant from the signed session. Client payloads and query parameters are not identity authorities.

### Current guarantees

- HMAC-signed, `HttpOnly`, `SameSite=Strict`, eight-hour session cookie.
- Fail-closed startup behavior when the signing key is absent or too short.
- API role checks and tenant-scoped store queries.
- Tenant-qualified run, result, decision, explanation, assignment, request, escalation, and intake relationships.
- Technical-manager routes that return operational or redacted metadata rather than claim content.

### Planned hardening

- PostgreSQL row-level security.
- A non-owner runtime database role.
- Session revocation and rotation.
- Password reset, invitation lifecycle, MFA, and production identity federation.
- Broader cross-tenant and indirect-object-reference tests.

Do not describe the current system as database-enforced RLS.

## Roles and permissions

| Action | Reviewer | Lead | Clinic admin | Technical manager |
|---|:---:|:---:|:---:|:---:|
| Read/create/recheck claims and record decisions | ✓ | ✓ | ✓ |  |
| Read review queues and ask the assistant | ✓ | ✓ | ✓ |  |
| Assign claims |  | ✓ | ✓ |  |
| Read analytics and audit |  | ✓ | ✓ |  |
| Manage the clinic team |  |  | ✓ |  |
| Read/manage operations |  |  | ✓ | ✓ |

This matrix is defined in `access.py`; UI navigation is only a presentation of it.

## Provision the first admin

Migrate the database and set `CLAIMGUARD_DATABASE_URL`, then run:

```powershell
uv run python -m claimguard.clinic.provision `
  --tenant-id clinic-demo `
  --clinic-name "Demo Clinic" `
  --email admin@example.test
```

The password prompt does not echo input and requires at least 12 characters. The command creates a clinic if needed, one user, and a clinic-admin membership. It refuses duplicate email addresses. Create later team members from **Team & Access**.

For a container-only installation:

```powershell
docker compose exec api python -m claimguard.clinic.provision --tenant-id clinic-demo --clinic-name "Demo Clinic" --email admin@example.test
```

Never place real credentials in a README, fixture, screenshot, or commit.

## Intake jobs

`intake_formats.py` and `workspaces.py` accept `envelope_json`, `csv_split`, `fhir_bundle`, or `auto` detection. The pilot payload limit is 64 KiB.

An intake job records source metadata and a normalized draft. Rejected or quarantined jobs do not execute rules. A user explicitly submits an accepted draft to create the validation run. This preserves a visible boundary between parsing and authoritative checking.

See [the Phase 1 examples](../../examples/phase1/README.md) for the exact file sets.

## Code map

| File | Responsibility |
|---|---|
| `access.py` | Roles, actions, permission matrix, tenant guard |
| `session.py` | Signed session creation and validation |
| `passwords.py` | Password hashing and verification |
| `provision.py` | Explicit first-admin bootstrap |
| `directory.py` | Clinic, user, membership, and department tables/services |
| `assignments.py` | Tenant-scoped claim ownership |
| `intake_formats.py` | Source detection and transport validation |
| `workspaces.py` | Requests, escalations, intake, configuration, and read models |

## Tests

```powershell
uv run pytest tests/clinic tests/integration -m "not llm and not e2e"
```

Every new clinic-owned query needs same-tenant success, cross-tenant refusal, wrong-role refusal, and inactive-user behavior where applicable.
