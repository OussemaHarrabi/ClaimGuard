# Audit integrity

`claimguard.audit` implements the canonical SHA-256 event-chain digest used by the PostgreSQL audit ledger.

[Back to the project README](../../README.md)

## What is recorded

The application records security- and workflow-relevant events such as claim checks, AI recommendations and provenance, review decisions, corrections, rechecks, assignments, intake state changes, and configuration changes. Event payloads are structured and tenant-scoped.

Each event links to the previous event hash:

```text
event N-1 chain_hash
        │
        ▼
prev_hash + canonical event fields + payload
        │
        ▼ SHA-256
event N chain_hash
```

Python and PostgreSQL must use the same canonical serialization and digest calculation. Migration `0001_initial_schema.sql` creates the ledger and protective triggers.

## Honest security claim

The ledger is append-only for normal application/database operations and **tamper-evident** through its chain. It is not an external write-once store and cannot protect itself against every database-superuser or infrastructure compromise. Production work still needs restricted database ownership, backups, external anchoring or export, retention policy, and alerting.

## Verify the chain

With PostgreSQL running and migrations applied:

```powershell
uv run python scripts/audit_replay.py
uv run pytest tests/integration -k "audit or hash"
```

The replay reconstructs stored activity and verifies every link. The technical-manager **Audit Integrity** page exposes a bounded operational view; clinic leads and admins use **Audit** for workflow history.

When adding an audited event, define a stable event name and payload, exclude secrets and unnecessary claim content, exercise it in a workflow test, and verify that replay still succeeds.
