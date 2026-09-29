"""Alembic environment for ClaimGuard — the driver for raw-SQL migrations.

Migrations live as raw SQL files under ``versions/`` (e.g.
``0001_initial_schema.sql``). Alembic only discovers revisions as Python
modules, so this env provides the wiring that turns those files into
Alembic-managed migrations:

* each file's header comment carries the Alembic identifiers
  (``revision = '0001'`` / ``down_revision = None``);
* pending files are applied in dependency order inside a single transaction;
* applied revisions are recorded in ``alembic_version`` exactly like a normal
  migration would.

The database URL comes from ``claimguard.config.get_settings()``
(``CLAIMGUARD_DATABASE_URL``); if the package is not importable the plain
``DATABASE_URL`` environment variable is used as a fallback.

Downgrades are not implemented: raw-SQL migrations are forward-only (drop and
re-create instead of downgrading).
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final

from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

# Make ``claimguard`` importable when alembic is run from the repo root even if
# the package has not been installed into the active environment.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

get_settings: Callable[[], Any] | None
try:
    from claimguard.config import get_settings
except ImportError:  # pragma: no cover — package not importable from this env
    get_settings = None

logger = logging.getLogger("alembic.env")

_REVISION_RE = re.compile(r"^\s*(?:--\s*)?revision\s*=\s*['\"]([^'\"]+)['\"]\s*$", re.MULTILINE)
_DOWN_REVISION_RE = re.compile(
    r"^\s*(?:--\s*)?down_revision\s*=\s*(?:None|['\"]([^'\"]+)['\"])\s*$",
    re.MULTILINE,
)
#: Revision ids are our own file-parsed tokens; anything outside this set is
#: rejected before it can be embedded into rendered SQL (offline mode).
_REVISION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_]+$")

#: Schema and qualified name of the Alembic bookkeeping table.
#:
#: They MUST be pinned. The connection's default ``search_path`` is
#: ``"$user", public`` and a schema named after the role (``claimguard``)
#: exists, so ``"$user"`` resolves to it. An *unqualified*
#: ``CREATE TABLE IF NOT EXISTS alembic_version`` is therefore created inside
#: ``claimguard``, and the unqualified ``SELECT`` that follows reads that new,
#: empty table. The runner then concludes that nothing has been applied and
#: re-runs migration 0001, which fails with
#: ``schema "claimguard" already exists`` — so a second
#: ``docker compose up`` could never start the API.
#:
#: The table has always lived in ``public`` (it was created before migration
#: 0001 brought the ``claimguard`` schema into existence), so pinning it there
#: keeps existing databases working and gives fresh ones the same home.
_VERSION_SCHEMA: Final = "public"
_VERSION_TABLE: Final = "public.alembic_version"


class SqlMigration:
    """One raw-SQL migration file with its Alembic identifiers.

    Plain class on purpose: Alembic executes ``env.py`` through
    ``importlib.util`` *without* registering it in ``sys.modules``, which
    breaks module-level ``@dataclass`` decoration — this class must not rely
    on module registration.
    """

    __slots__ = ("down_revision", "path", "revision")

    def __init__(self, *, path: Path, revision: str, down_revision: str | None) -> None:
        self.path = path
        self.revision = revision
        self.down_revision = down_revision

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SqlMigration):
            return NotImplemented
        return (
            self.path == other.path
            and self.revision == other.revision
            and self.down_revision == other.down_revision
        )

    def __hash__(self) -> int:
        return hash((self.path, self.revision, self.down_revision))

    def __repr__(self) -> str:
        return (
            f"SqlMigration(path={self.path.name!r}, revision={self.revision!r}, "
            f"down_revision={self.down_revision!r})"
        )


def _safe_revision_literal(revision: str) -> str:
    """Quote a revision id for rendered SQL, rejecting anything unsafe."""

    if _REVISION_TOKEN_RE.fullmatch(revision) is None:
        raise ValueError(f"revision id {revision!r} is not a safe SQL literal")
    return f"'{revision}'"


def _versions_dir() -> Path:
    return Path(__file__).resolve().parent / "versions"


def _database_url() -> str:
    """Resolve the database URL: application settings first, then environment."""

    if get_settings is not None:
        return get_settings().database_url
    url = os.environ.get("DATABASE_URL")
    if url is None:
        raise RuntimeError(
            "No database URL available: neither claimguard.config (CLAIMGUARD_DATABASE_URL) "
            "nor DATABASE_URL provided one."
        )
    return url


def _load_migration(path: Path) -> SqlMigration:
    """Parse the Alembic revision identifiers from a migration file's header."""

    header = path.read_text(encoding="utf-8")
    revision_match = _REVISION_RE.search(header)
    if revision_match is None:
        raise ValueError(
            f"migration {path.name} has no 'revision = ...' header line; "
            "add '-- revision = <id>' to the file."
        )
    down_match = _DOWN_REVISION_RE.search(header)
    return SqlMigration(
        path=path,
        revision=revision_match.group(1),
        down_revision=down_match.group(1) if down_match and down_match.group(1) else None,
    )


def _order_migrations(migrations: Sequence[SqlMigration]) -> list[SqlMigration]:
    """Topologically sort migrations by their ``down_revision`` edges.

    Deterministic: ties break on the revision id. Raises when the graph is
    cyclic or a ``down_revision`` points at a missing file.
    """

    remaining = {migration.revision: migration for migration in migrations}
    if len(remaining) != len(migrations):
        raise ValueError("duplicate revision ids across migration files")
    applied: set[str] = set()
    ordered: list[SqlMigration] = []
    while remaining:
        ready = sorted(
            (
                migration
                for migration in remaining.values()
                if migration.down_revision is None or migration.down_revision in applied
            ),
            key=lambda migration: migration.revision,
        )
        if not ready:
            stuck = ", ".join(sorted(remaining))
            raise ValueError(
                "cannot order migrations: cyclic or missing down_revision for: " + stuck
            )
        for migration in ready:
            ordered.append(migration)
            applied.add(migration.revision)
            remaining.pop(migration.revision)
    return ordered


def _has_sql_content(statement: str) -> bool:
    """True when the fragment holds any token beyond whitespace and comments."""

    index = 0
    length = len(statement)
    while index < length:
        char = statement[index]
        if char.isspace():
            index += 1
        elif statement.startswith("--", index):
            newline = statement.find("\n", index)
            index = length if newline == -1 else newline + 1
        elif statement.startswith("/*", index):
            depth = 1
            index += 2
            while index < length and depth:
                if statement.startswith("/*", index):
                    depth += 1
                    index += 2
                elif statement.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
        else:
            return True
    return False


def _split_sql_statements(sql: str) -> list[str]:
    """Split a SQL script on top-level semicolons, honouring PostgreSQL quoting.

    Single-quoted strings (``'...'`` with ``''`` and ``E'\\...'`` escapes),
    double-quoted identifiers, ``--`` line comments, nested ``/* ... */`` block
    comments and dollar-quoted bodies (``$$ ... $$`` / ``$tag$ ... $tag$``) are
    preserved verbatim, so semicolons inside function bodies never split a
    statement.
    """

    statements: list[str] = []
    start = 0
    index = 0
    length = len(sql)
    state = "plain"
    block_depth = 0
    backslash_escapes = False
    dollar_tag = ""

    while index < length:
        char = sql[index]
        nxt = sql[index + 1] if index + 1 < length else ""

        if state == "plain":
            if char == "-" and nxt == "-":
                state = "line_comment"
                index += 2
            elif char == "/" and nxt == "*":
                state = "block_comment"
                block_depth = 1
                index += 2
            elif char in "eE" and nxt == "'":
                state = "single_quote"
                backslash_escapes = True
                index += 2
            elif char == "'":
                state = "single_quote"
                backslash_escapes = False
                index += 1
            elif char == '"':
                state = "double_quote"
                index += 1
            elif char == "$":
                tag_end = sql.find("$", index + 1)
                if tag_end != -1 and not any(c.isspace() for c in sql[index + 1 : tag_end]):
                    dollar_tag = sql[index : tag_end + 1]
                    body_end = sql.find(dollar_tag, tag_end + 1)
                    if body_end == -1:
                        raise ValueError(f"unterminated dollar-quoted body {dollar_tag!r}")
                    index = body_end + len(dollar_tag)
                else:
                    index += 1
            elif char == ";":
                statements.append(sql[start:index])
                index += 1
                start = index
            else:
                index += 1
        elif state == "line_comment":
            if char == "\n":
                state = "plain"
            index += 1
        elif state == "block_comment":
            if char == "/" and nxt == "*":
                block_depth += 1
                index += 2
            elif char == "*" and nxt == "/":
                block_depth -= 1
                index += 2
                if block_depth == 0:
                    state = "plain"
            else:
                index += 1
        elif state == "single_quote":
            if (char == "\\" and backslash_escapes) or (char == "'" and nxt == "'"):
                index += 2
            elif char == "'":
                state = "plain"
                index += 1
            else:
                index += 1
        else:  # double_quote
            if char == '"' and nxt == '"':
                index += 2
            elif char == '"':
                state = "plain"
                index += 1
            else:
                index += 1

    statements.append(sql[start:])
    return [s for s in statements if _has_sql_content(s)]


def _ensure_version_table(connection: Connection) -> None:
    """Create the bookkeeping table in its pinned schema, never in search_path order."""

    connection.exec_driver_sql(
        # _VERSION_TABLE is a repository-owned constant; no external input is interpolated.
        f"CREATE TABLE IF NOT EXISTS {_VERSION_TABLE} ("
        "version_num VARCHAR(32) NOT NULL,"
        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    )


def _applied_revisions(connection: Connection) -> set[str]:
    result = connection.execute(
        # _VERSION_TABLE is a repository-owned constant; no external input is interpolated.
        text(f"SELECT version_num FROM {_VERSION_TABLE} ORDER BY version_num")  # noqa: S608
    )
    return {str(row) for row in result.scalars()}


def _record_revision(connection: Connection, revision: str) -> None:
    connection.execute(
        # _VERSION_TABLE is a repository-owned constant; no external input is interpolated.
        text(f"INSERT INTO {_VERSION_TABLE} (version_num) VALUES (:version_num)"),  # noqa: S608
        {"version_num": revision},
    )


def _apply_migration(connection: Connection, migration: SqlMigration) -> None:
    """Execute one migration file, statement by statement, on the connection.

    Uses the RAW DBAPI cursor deliberately.

    SQLAlchemy's `exec_driver_sql` still routes through psycopg 3's client-side
    parameter handling, which treats a literal `%` as a placeholder. Migration
    0001's `RAISE EXCEPTION '... event % cannot be updated ...'` contains such a
    literal, and applying it via exec_driver_sql fails with
    "incomplete placeholder: '%'". Migration DDL is trusted, static, in-repo
    text with no user input, so executing it through the raw driver is both
    correct and safe.
    """

    sql = migration.path.read_text(encoding="utf-8")
    statements = _split_sql_statements(sql)
    if not statements:
        raise ValueError(f"migration {migration.path.name} contains no executable SQL")

    raw = connection.connection.dbapi_connection  # type: ignore[union-attr]
    cursor = raw.cursor()  # type: ignore[union-attr]
    try:
        for number, statement in enumerate(statements, start=1):
            logger.info("  %s: statement %d/%d", migration.revision, number, len(statements))
            cursor.execute(statement)
    finally:
        cursor.close()


def _apply_pending(connection: Connection) -> None:
    """Apply every pending migration, record each in ``alembic_version``."""

    _ensure_version_table(connection)
    applied = _applied_revisions(connection)
    migrations = _order_migrations(
        [_load_migration(path) for path in sorted(_versions_dir().glob("*.sql"))]
    )
    for migration in migrations:
        if migration.revision in applied:
            logger.info("migration %s already applied; skipping", migration.revision)
            continue
        logger.info("applying migration %s (%s)", migration.revision, migration.path.name)
        _apply_migration(connection, migration)
        _record_revision(connection, migration.revision)


def run_migrations_offline() -> None:
    """Render the pending migrations to the output buffer (``--sql`` mode)."""

    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=_VERSION_SCHEMA,
    )
    output = context.get_context().output_buffer
    migrations = _order_migrations(
        [_load_migration(path) for path in sorted(_versions_dir().glob("*.sql"))]
    )
    output.write("-- ClaimGuard migrations (offline render: alembic upgrade head --sql)\n")
    for migration in migrations:
        output.write(f"-- === {migration.revision}: {migration.path.name} ===\n")
        sql = migration.path.read_text(encoding="utf-8")
        output.write(sql)
        if not sql.rstrip().endswith(";"):
            output.write(";\n")
        output.write("\n")
    output.write("-- version bookkeeping (identical to online mode)\n")
    output.write(
        # _VERSION_TABLE is a repository-owned constant; not external input.
        f"CREATE TABLE IF NOT EXISTS {_VERSION_TABLE} (\n"
        "    version_num VARCHAR(32) NOT NULL,\n"
        "    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)\n"
        ");\n"
    )
    for migration in migrations:
        # Revision ids are parsed from repository-owned migration files and
        # constrained to [A-Za-z0-9_]+ by _safe_revision_literal(), so the
        # interpolation below cannot carry attacker-controlled input.
        literal = _safe_revision_literal(migration.revision)
        # `literal` is repo-owned and constrained to [A-Za-z0-9_]+ by
        # _safe_revision_literal(); not attacker input.
        stmt = f"INSERT INTO {_VERSION_TABLE} (version_num) VALUES ({literal});\n"  # noqa: S608
        output.write(stmt)
    output.flush()


def run_migrations_online() -> None:
    """Connect to the database and apply all pending SQL migrations."""

    engine = create_engine(_database_url(), poolclass=NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
            version_table_schema=_VERSION_SCHEMA,
        )
        with context.begin_transaction():
            _apply_pending(connection)
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
