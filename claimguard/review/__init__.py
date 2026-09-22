"""The ClaimGuard reviewer workflow: runs, review queue, decisions and audit.

The package turns the frozen deterministic engine into something a claims
officer can actually work with, without ever letting a human *or* a model
rewrite a check result:

*   :mod:`claimguard.review.models` — the reviewer contracts. The 15-key engine
    record (validated by the engine's own model), a run's identity and versions,
    the finding view with its review state, and exactly the pack's 7-key
    ``review_event`` decided by a four-action state machine.
*   :mod:`claimguard.review.store` — PostgreSQL persistence for runs, the 15
    records per run and the append-only decision ledger, over migration
    ``0002_review_workflow.sql`` (additive; migration 0001 is untouched).
*   :mod:`claimguard.review.audit_events` — run-level and decision-level events
    appended to the EXISTING hash-chained ``claimguard.audit_events`` table. The
    0001 trigger remains the single owner of the chain hash.
*   :mod:`claimguard.review.app` — the FastAPI surface: submit, read a run's 15
    results, list the queue with unresolved counts, record a decision, recheck a
    corrected claim as a new version.

Two invariants hold everywhere in the package: a correction is a **new run
version** (the original run, its records and its decisions are never mutated, and
the database refuses to update them), and nothing here approves, denies, pays or
adjudicates — a decision is a reviewer's note about a check.
"""

from __future__ import annotations

from claimguard.review import audit_events, models, store
from claimguard.review.app import create_app
from claimguard.review.models import (
    REVIEW_ACTIONS,
    REVIEW_EVENT_KEYS,
    IllegalReviewTransitionError,
    ReviewAction,
    ReviewDecisionEvent,
    ReviewStatus,
)
from claimguard.review.store import ReviewStore, build_engine, envelope_digest, resolve_dsn

__all__ = [
    "REVIEW_ACTIONS",
    "REVIEW_EVENT_KEYS",
    "IllegalReviewTransitionError",
    "ReviewAction",
    "ReviewDecisionEvent",
    "ReviewStatus",
    "ReviewStore",
    "audit_events",
    "build_engine",
    "create_app",
    "envelope_digest",
    "models",
    "resolve_dsn",
    "store",
]
