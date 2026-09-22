"""P0-3 integration test: Python hash == SQL trigger hash, on live PostgreSQL.

WHY THIS TEST EXISTS
--------------------
The audit hash chain has two implementations that MUST agree bit-for-bit:

  * `claimguard/audit/chain.py::chain_hash` (Python, used by verification)
  * `claimguard.audit_chain_insert()` (the Postgres BEFORE INSERT trigger,
    declared in `09` §Part B as the SINGLE CANONICAL OWNER)

If they disagree, nightly verification reports every link as broken while the SQL
verifier reports success — or vice versa. Either way the audit story collapses.

THE RISK THIS TEST PINS
-----------------------
Timestamps. The trigger hashes `at::text`, which renders in the session
`TimeZone` AND omits the fractional part when it is zero. Python's default
formatting emits six fractional digits always. Discovered here: that single
difference made the two implementations disagree on every whole-second
timestamp. Nothing else in the code reveals it.

REQUIREMENTS
------------
    docker compose up -d db
    export CLAIMGUARD_DATABASE_URL='postgresql+psycopg://claimguard:claimguard@localhost:5432/claimguard'
    uv run alembic upgrade head

Skipped automatically when the DB is unreachable, so the default run stays fast.

SCHEMA NOTES (from migration 0001 — do not guess these)
-------------------------------------------------------
  * `kind` uses UNDERSCORE values ('claim_received', 'finding_created', ...).
  * `finding_ids` is `TEXT[] NOT NULL DEFAULT '{}'` — pass `[]`, never None.
  * `verify_audit_chain()` returns (broken_at, event_id, expected, stored),
    one row per broken link and an EMPTY set when the chain is intact.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest
from claimguard.audit.chain import chain_hash

logger = logging.getLogger(__name__)

DSN = os.getenv(
    "CLAIMGUARD_DATABASE_URL",
    "postgresql+psycopg://claimguard:claimguard@localhost:5432/claimguard",
)
# psycopg.connect wants the plain scheme; we set the UTC session ourselves.
RAW_DSN = os.getenv("DATABASE_URL") or DSN.replace("postgresql+psycopg://", "postgresql://")

INSERT_SQL = """
    INSERT INTO claimguard.audit_events
        (event_id, at, kind, claim_ref, trace_id, decision, reason_code,
         finding_ids, rule_version, model_version, prev_hash)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def _db_available(retries: int = 5, delay: float = 1.0) -> bool:
    """Probe for a reachable Postgres, with retries.

    Retries matter: in CI the service container reports 'running' before
    Postgres has finished initialising, so a single fast probe fails and every
    integration test silently skips — or this module errors during collection
    because the probe raised.
    """
    import time

    for attempt in range(retries):
        try:
            with psycopg.connect(RAW_DSN, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            return True
        except psycopg.Error:
            if attempt == retries - 1:
                return False
            time.sleep(delay)
    return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _db_available(), reason="PostgreSQL not reachable"),
]


@pytest.fixture()
def conn() -> psycopg.Connection:  # type: ignore[type-arg]
    """Live connection, autocommit ON.

    Autocommit matters: the append-only test issues its UPDATE in a statement
    AFTER the INSERT. Without a commit the row is invisible, the UPDATE matches
    zero rows, the trigger never fires, and the test passes for the wrong reason.
    """
    connection = psycopg.connect(RAW_DSN, autocommit=True)
    # CRITICAL: the trigger renders at::text in the session TimeZone; Python
    # formats as UTC. Without this the digests disagree.
    connection.execute("SET TIME ZONE 'UTC'")
    yield connection  # type: ignore[misc]
    connection.close()


@pytest.fixture(autouse=True)
def _cleanup(conn: psycopg.Connection) -> Iterator[None]:  # type: ignore[type-arg]
    """Remove only rows this module creates, so the DB stays usable."""
    yield
    try:
        conn.execute("ALTER TABLE claimguard.audit_events DISABLE TRIGGER trg_audit_no_modify")
        conn.execute(
            "DELETE FROM claimguard.audit_events "
            "WHERE trace_id IN ('trace-parity-1','trace-parity-2','trace-chain',"
            "'trace-append','trace-verify','trace-direct')"
        )
        conn.execute("ALTER TABLE claimguard.audit_events ENABLE TRIGGER trg_audit_no_modify")
    except psycopg.Error as exc:  # pragma: no cover - cleanup best effort
        logger.debug("audit parity cleanup failed: %s", exc)


def _chain_head(conn: psycopg.Connection) -> str:  # type: ignore[type-arg]
    """The ledger head right now — what the next insert must chain from.

    The ledger is append-only and shared (CI's fresh database, a developer's
    long-lived one, and the app writing real runs), so the head is a moving
    target and asserting a literal "genesis" would only ever hold on a virgin
    table. Reading it makes these checks test the trigger's contract instead of
    the emptiness of the table.
    """
    row = conn.execute(
        "SELECT COALESCE((SELECT chain_hash FROM claimguard.audit_events "
        "ORDER BY at DESC, event_id DESC LIMIT 1), 'genesis')"
    ).fetchone()
    assert row is not None
    return str(row[0])


def test_python_hash_matches_trigger_hash(conn: psycopg.Connection) -> None:  # type: ignore[type-arg]
    """The core P0-3 assertion: both implementations produce the same digest."""
    at = datetime(2026, 9, 5, 12, 34, 56, 789012, tzinfo=UTC)
    event_id = uuid.uuid4()

    conn.execute(
        INSERT_SQL,
        (
            event_id,
            at,
            "finding_created",
            "CLM-0042",
            "trace-parity-1",
            "A-001",
            "approve",
            ["f1", "f2"],
            "1",
            "1.0",
            "genesis",
        ),
    )

    row = conn.execute(
        "SELECT prev_hash, chain_hash FROM claimguard.audit_events WHERE event_id = %s", (event_id,)
    ).fetchone()
    assert row is not None, "trigger did not populate chain_hash"
    stored_prev, stored_hash = str(row[0]), str(row[1])

    # The trigger chains from whatever the current head is, so the expectation is
    # seeded with the prev_hash the trigger actually stored. Asserting a literal
    # "genesis" would only hold on a virgin table, which would couple this check to
    # ledger emptiness instead of to the serialisation contract it exists to prove.
    expected = chain_hash(
        prev_hash=stored_prev,
        at=at,
        claim_ref="CLM-0042",
        trace_id="trace-parity-1",
        decision="A-001",
        reason_code="approve",
        finding_ids=["f1", "f2"],
        model_version="1.0",
    )

    assert stored_hash == expected, (
        "P0-3 VIOLATION: the SQL trigger and Python chain_hash disagree.\n"
        f"  trigger: {stored_hash}\n"
        f"  python : {expected}\n"
        "Most likely cause is at::text rendering — confirm the app connection "
        "sets TimeZone=UTC."
    )


def test_whole_second_timestamp_also_matches(conn: psycopg.Connection) -> None:  # type: ignore[type-arg]
    """Regression guard for the fractional-second bug.

    Postgres omits '.000000' for a whole second; naive Python formatting does
    not. This test exists so that divergence cannot return.
    """
    at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)  # no microseconds
    event_id = uuid.uuid4()

    conn.execute(
        INSERT_SQL,
        (
            event_id,
            at,
            "claim_received",
            None,
            "trace-parity-2",
            None,
            None,
            [],
            None,
            None,
            "genesis",
        ),
    )

    row = conn.execute(
        "SELECT prev_hash, chain_hash FROM claimguard.audit_events WHERE event_id = %s", (event_id,)
    ).fetchone()
    assert row is not None

    expected = chain_hash(
        prev_hash=str(row[0]),
        at=at,
        claim_ref=None,
        trace_id="trace-parity-2",
        decision=None,
        reason_code=None,
        finding_ids=[],
        model_version=None,
    )
    assert str(row[1]) == expected


def test_trigger_chains_from_previous_row(conn: psycopg.Connection) -> None:  # type: ignore[type-arg]
    """The second insert must chain from the first insert's stored hash."""
    # Far-future timestamps: the trigger chains from the newest event in the
    # ledger, so this keeps the module's own two events at the head regardless of
    # what else the (shared, append-only) table contains. That makes the
    # inter-event chaining assertion below a property of the trigger rather than of
    # how empty the database happens to be.
    base = datetime(2999, 3, 1, 9, 0, 0, tzinfo=UTC)
    head_before: list[str] = []

    for i in range(2):
        head = _chain_head(conn)
        head_before.append(head)
        conn.execute(
            INSERT_SQL,
            (
                uuid.uuid4(),
                base.replace(second=i),
                "validated",
                "CLM-CHAIN",
                "trace-chain",
                None,
                None,
                [],
                None,
                None,
                head,
            ),
        )

    rows = conn.execute(
        "SELECT prev_hash, chain_hash FROM claimguard.audit_events "
        "WHERE trace_id = 'trace-chain' ORDER BY at, event_id"
    ).fetchall()
    assert len(rows) == 2
    # The first event links into whatever was already there...
    assert rows[0][0] == head_before[0]
    # ...and the second links to the first, which is the chaining contract.
    assert rows[1][0] == rows[0][1], "second event did not chain from the first"


def test_audit_events_are_append_only(conn: psycopg.Connection) -> None:  # type: ignore[type-arg]
    """UPDATE and DELETE must be blocked — this is the audit guarantee."""
    event_id = uuid.uuid4()
    conn.execute(
        INSERT_SQL,
        (
            event_id,
            datetime(2026, 4, 1, tzinfo=UTC),
            "claim_received",
            "CLM-APPEND",
            "trace-append",
            None,
            None,
            [],
            None,
            None,
            "genesis",
        ),
    )

    # Sanity: the row is actually there, so the UPDATE below really tests the
    # trigger rather than silently matching zero rows.
    row = conn.execute(
        "SELECT count(*) FROM claimguard.audit_events WHERE event_id = %s", (event_id,)
    ).fetchone()
    assert row is not None, "sanity row missing — the UPDATE below would test nothing"
    assert row[0] == 1

    with pytest.raises(Exception, match="append-only"):
        conn.execute(
            "UPDATE claimguard.audit_events SET decision = 'TAMPERED' WHERE event_id = %s",
            (event_id,),
        )

    with pytest.raises(Exception, match="append-only"):
        conn.execute("DELETE FROM claimguard.audit_events WHERE event_id = %s", (event_id,))


def test_verify_function_reports_broken_link(conn: psycopg.Connection) -> None:  # type: ignore[type-arg]
    """The SQL verifier must detect a forgery that bypassed the trigger."""
    event_id = uuid.uuid4()
    conn.execute(
        INSERT_SQL,
        (
            event_id,
            datetime(2026, 5, 1, tzinfo=UTC),
            "claim_received",
            "CLM-VERIFY",
            "trace-verify",
            None,
            None,
            [],
            None,
            None,
            "genesis",
        ),
    )

    # Forge content while keeping the stored hash, simulating a bypass path.
    conn.execute("ALTER TABLE claimguard.audit_events DISABLE TRIGGER trg_audit_no_modify")
    conn.execute(
        "UPDATE claimguard.audit_events SET decision = 'FORGED' WHERE event_id = %s",
        (event_id,),
    )
    conn.execute("ALTER TABLE claimguard.audit_events ENABLE TRIGGER trg_audit_no_modify")

    # Returns (broken_at, event_id, expected, stored) — one row per broken link.
    broken = conn.execute("SELECT * FROM claimguard.verify_audit_chain()").fetchall()
    assert broken, "verify_audit_chain() did not detect a forged row"
    assert broken[0][2] != broken[0][3], "reported row should show expected != stored"
