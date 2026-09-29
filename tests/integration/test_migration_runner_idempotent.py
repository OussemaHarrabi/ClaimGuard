"""Regression: the migration runner must be idempotent across repeated runs.

The runner used to create its bookkeeping table with an *unqualified*
``CREATE TABLE IF NOT EXISTS alembic_version``. The connection's ``search_path``
is ``"$user", public`` and a schema named after the role (``claimguard``)
exists, so ``"$user"`` resolves to it: the table was created inside
``claimguard``, and the unqualified ``SELECT`` that followed read that brand-new,
empty table. The runner therefore concluded that nothing had been applied,
re-ran migration 0001, and died with ``schema "claimguard" already exists``.

That is not a cosmetic failure: the compose ``api`` service waits for the
one-shot ``migrate`` service to complete successfully, so a second
``docker compose up`` could never start the API.

These tests run ``alembic upgrade head`` twice and assert both runs succeed, and
that the version table lives in its pinned schema rather than in the role's
schema.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg
import pytest

#: Repository root — ``alembic.ini`` is resolved relative to the cwd.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Same resolution as tests/integration/test_audit_trigger_parity.py, so both
#: modules talk to the same database.
DSN = os.getenv(
    "CLAIMGUARD_DATABASE_URL",
    "postgresql+psycopg://claimguard:claimguard@localhost:5432/claimguard",
)
#: psycopg.connect wants the plain scheme.
RAW_DSN = os.getenv("DATABASE_URL") or DSN.replace("postgresql+psycopg://", "postgresql://")


def _db_available(retries: int = 5, delay: float = 1.0) -> bool:
    """Probe for a reachable Postgres, with retries.

    Retries matter in CI, where the service container reports 'running' before
    Postgres has finished initialising.
    """
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


def _upgrade_head() -> subprocess.CompletedProcess[str]:
    """Run ``alembic upgrade head`` in a child process against the test DSN."""
    env = {**os.environ, "CLAIMGUARD_DATABASE_URL": DSN}
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )


def test_upgrade_head_is_idempotent() -> None:
    """A repeated ``upgrade head`` must be a no-op, not a re-application."""
    first = _upgrade_head()
    assert first.returncode == 0, f"first upgrade failed:\n{first.stdout}\n{first.stderr}"

    second = _upgrade_head()
    assert second.returncode == 0, (
        "the second `alembic upgrade head` failed, so the migration runner is "
        f"not idempotent:\n{second.stdout}\n{second.stderr}"
    )


def test_version_table_is_pinned_to_the_public_schema() -> None:
    """Guard the root cause: bookkeeping must not follow the search path."""
    _upgrade_head()
    with psycopg.connect(RAW_DSN) as conn:
        schemas = [
            str(row[0])
            for row in conn.execute(
                "SELECT table_schema FROM information_schema.tables "
                "WHERE table_name = 'alembic_version' "
                "ORDER BY table_schema"
            ).fetchall()
        ]
    assert schemas, "alembic_version is missing after `upgrade head`"
    assert "public" in schemas, f"alembic_version is not in public: {schemas}"
    assert "claimguard" not in schemas, (
        "the version table was created in the role's schema instead of the "
        f"pinned schema, which is the defect being guarded: {schemas}"
    )
