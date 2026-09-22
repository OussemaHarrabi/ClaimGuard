"""Fixtures for the review-workflow tests.

DATABASE POLICY
---------------
The unit tests (``test_models.py``, ``test_app_config.py``) need nothing and
always run. The integration tests need PostgreSQL; they carry ``requires_db``
(below) and skip automatically when it is unreachable, so a default
``uv run pytest`` stays fast and green on a laptop with no database.

When the database IS reachable, the ``store`` fixture applies pending migrations
(``alembic upgrade head``, the same command CI runs) before the first query, so a
reachable database is sufficient — no manual setup step can silently turn the
integration tests into skips.

CLEANUP
-------
Every row a test creates is removed at teardown, through the ``sandbox`` fixture.
The review tables are immutable by design (that is the point of migration 0002),
so cleanup has to stand the guards down for the moment it deletes — exactly what
``tests/integration/test_audit_trigger_parity.py`` does for the audit ledger. Rows
are selected by the claim ids the test registered, so nothing else is touched.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from claimguard.config import get_settings
from claimguard.review import audit_events
from claimguard.review.app import create_app
from claimguard.review.store import DECISIONS, RUNS, ReviewStore, build_engine
from sqlalchemy import Engine, delete, select
from sqlalchemy.engine import Connection

from tests.edu import RULES_DIR, base_claim

REPO_ROOT: Final = Path(__file__).resolve().parents[2]

#: The DSN used when neither ``CLAIMGUARD_DATABASE_URL`` (the setting
#: ``claimguard.config`` reads) nor ``DATABASE_URL`` is exported. Matches
#: ``docker-compose.yml`` and the CI service container.
DEFAULT_DSN: Final = "postgresql+psycopg://claimguard:claimguard@localhost:5432/claimguard"

#: The rule every review test decides about: R003 is the one the fixture claim
#: fails (coverage ends 2026-03-09, service date 2026-03-10), severity high.
FAILING_RULE: Final = "R003"


def _dsn() -> str:
    """The test DSN, normalised to a SQLAlchemy URL with the psycopg3 driver."""
    raw = os.environ.get("CLAIMGUARD_DATABASE_URL") or os.environ.get("DATABASE_URL") or DEFAULT_DSN
    return raw.replace("postgresql://", "postgresql+psycopg://", 1)


TEST_DSN: Final = _dsn()
RAW_DSN: Final = TEST_DSN.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache(maxsize=1)
def db_available(retries: int = 4, delay: float = 0.75) -> bool:
    """Probe for a reachable PostgreSQL, with retries, once per session.

    Retries because a fresh CI service container reports as running before
    Postgres accepts connections; a single fast probe would turn every
    integration test into a silent skip.
    """
    for attempt in range(retries):
        try:
            with psycopg.connect(RAW_DSN, connect_timeout=3):
                return True
        except psycopg.Error:
            if attempt == retries - 1:
                return False
            time.sleep(delay)
    return False  # pragma: no cover - the loop always returns


#: Skip marker for the modules that need the database (see the package docstring).
requires_db = pytest.mark.skipif(
    not db_available(),
    reason=(
        f"PostgreSQL is not reachable at {RAW_DSN}; "
        "start it with `docker compose up -d db` to run these tests"
    ),
)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """A UTC-pinned engine for the test DSN."""
    created = build_engine(TEST_DSN)
    yield created
    created.dispose()


@pytest.fixture(scope="session")
def store(engine: Engine) -> ReviewStore:
    """A store whose tables exist (applying pending migrations when needed)."""
    review_store = ReviewStore(engine)
    if review_store.schema_revision() is None:
        _apply_migrations()
    review_store.ensure_schema()
    return review_store


def _apply_migrations() -> None:
    """Run ``alembic upgrade head`` against the test DSN (the CI/dev command)."""
    os.environ["CLAIMGUARD_DATABASE_URL"] = TEST_DSN
    # ``get_settings`` is cached, and env.py resolves the URL through it.
    get_settings.cache_clear()
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "claimguard" / "db" / "migrations"))
    command.upgrade(config, "head")


def _copy(envelope: dict[str, Any]) -> dict[str, Any]:
    """A deep copy through JSON, so a correction cannot alias the original."""
    return json.loads(json.dumps(envelope))


class Sandbox:
    """Registers the claim ids a test creates, and removes their rows afterwards."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self.claim_ids: list[str] = []

    def register(self, envelope: dict[str, Any]) -> dict[str, Any]:
        """Register one envelope's claim id for cleanup and return it unchanged."""
        claim_id = envelope.get("claim_id")
        if not isinstance(claim_id, str):  # pragma: no cover - test data is ours
            raise AssertionError("test envelope has no claim_id")
        if claim_id not in self.claim_ids:
            self.claim_ids.append(claim_id)
        return envelope

    def claim(self) -> dict[str, Any]:
        """A clean pack-conformant claim with a unique id, registered for cleanup."""
        envelope = base_claim()
        envelope["claim_id"] = f"CG-REVIEW-{uuid.uuid4().hex[:10]}"
        envelope["invoice_number"] = f"INV-{envelope['claim_id']}"
        envelope["coverage"]["coverage_id"] = f"COV-{envelope['claim_id']}"
        return self.register(envelope)

    def coverage_lapse(self) -> dict[str, Any]:
        """A claim whose only failing check is R003 (coverage ends before service)."""
        envelope = self.claim()
        envelope["coverage"]["end_date"] = "2026-03-09"  # the service date is 2026-03-10
        return envelope

    def corrected(self, envelope: dict[str, Any]) -> dict[str, Any]:
        """The same claim with the coverage period corrected in the source data."""
        fixed = _copy(envelope)
        fixed["coverage"]["end_date"] = "2026-12-31"
        return self.register(fixed)

    def purge(self) -> None:
        """Delete every row this test created (guards stand down for the moment)."""
        if self.claim_ids:
            purge_claims(self._engine, self.claim_ids)


@pytest.fixture
def sandbox(engine: Engine) -> Iterator[Sandbox]:
    """Per-test claim factory whose rows are removed at teardown."""
    box = Sandbox(engine)
    yield box
    box.purge()


def _claim_run_ids(connection: Connection, claim_ids: Sequence[str]) -> list[str]:
    """The claims' run ids, newest version first (the safe deletion order)."""
    rows = connection.execute(
        select(RUNS.c.run_id)
        .where(RUNS.c.claim_id.in_(list(claim_ids)))
        .order_by(RUNS.c.version.desc())
    ).all()
    return [str(row.run_id) for row in rows]


def purge_claims(engine: Engine, claim_ids: Sequence[str]) -> None:
    """Remove every review row of ``claim_ids``, newest version first.

    Newest first because ``rule_runs.supersedes_run_id`` is ``ON DELETE SET NULL``:
    deleting an older version while a newer one still references it would try to
    update the newer row, which ``trg_rule_runs_no_update`` refuses. The
    append-only guards of ``review_decisions`` and ``audit_events`` are stood down
    for the statements that delete, and restored immediately.
    """
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE claimguard.review_decisions DISABLE TRIGGER trg_review_decisions_no_modify"
        )
        connection.exec_driver_sql(
            "ALTER TABLE claimguard.audit_events DISABLE TRIGGER trg_audit_no_modify"
        )
        run_ids = _claim_run_ids(connection, claim_ids)
        connection.execute(delete(DECISIONS).where(DECISIONS.c.claim_id.in_(list(claim_ids))))
        for run_id in run_ids:
            connection.execute(delete(RUNS).where(RUNS.c.run_id == run_id))
        connection.execute(
            delete(audit_events.AUDIT_EVENTS).where(
                audit_events.AUDIT_EVENTS.c.claim_ref.in_(run_ids)
            )
        )
        connection.exec_driver_sql(
            "ALTER TABLE claimguard.audit_events ENABLE TRIGGER trg_audit_no_modify"
        )
        connection.exec_driver_sql(
            "ALTER TABLE claimguard.review_decisions ENABLE TRIGGER trg_review_decisions_no_modify"
        )


@pytest.fixture
async def client(store: ReviewStore) -> AsyncIterator[httpx.AsyncClient]:
    """An in-process HTTP client for the review API (no server, no network)."""
    app = create_app(store=store, rules_dir=RULES_DIR)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://review.test") as http:
        yield http
