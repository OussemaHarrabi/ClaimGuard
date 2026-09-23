"""``claimguard status`` — can this checkout run anything, and under which contract?

Three questions, each answered from the artefact itself rather than from a promise:

* **which contract is in force** — the decision record that says the mentor pack's ``R001``-
  ``R015`` rulebook is the graded contract, its status and date, and a SHA-256 of the exact
  file on disk (so "which contract" is a hash, not a memory);
* **which rule catalogue** the engine and the API would load, and how many rules it holds;
* **whether the database is reachable** and which migration revision it carries.

Nothing here is a substitute for the gates: a ready status means the commands can run, not
that they pass. Exit code 0 when every check is ready, 1 when any of them is not.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Final

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from claimguard.cli.tooling import REPO_ROOT
from claimguard.edu.envelope import RULE_IDS, RULE_VERSION
from claimguard.edu.policy import RuleContext, RuleDirError
from claimguard.review.app import PACK_ROOT_ENV, RULES_DIR_ENV, resolve_rules_dir
from claimguard.review.store import ReviewStore, build_engine, resolve_dsn

EXIT_READY: Final = 0
EXIT_DEGRADED: Final = 1

#: The decision record that fixes which contract is graded (docs/10). Its status line and its
#: digest are quoted, not interpreted.
CONTRACT_DOC: Final = Path("docs") / "10-ADR-Starter-Pack-Authority.md"

#: How much of the digest to print: enough to compare by eye, short enough for one line.
DIGEST_CHARS: Final = 16

#: Width of the left-hand column, so the three answers line up.
LABEL_WIDTH: Final = 20

#: An ADR's header block is its first few lines; scanning further would risk quoting prose.
HEADER_LINES: Final = 20


def run(args: argparse.Namespace) -> int:
    """Report readiness; ``status`` takes no options, so ``args`` is unused."""
    del args
    _line("ClaimGuard AI", "environment status")
    _line("", "")
    contract_ready = _report_contract()
    rules_ready = _report_catalogue()
    database_ready = _report_database()
    _line("", "")
    ready = contract_ready and rules_ready and database_ready
    print("RESULT: ready" if ready else "RESULT: degraded")
    return EXIT_READY if ready else EXIT_DEGRADED


def _report_contract() -> bool:
    """Which contract is in force, and the digest of the record that says so."""
    path = REPO_ROOT / CONTRACT_DOC
    if not path.is_file():
        _line("contract in force", f"NOT FOUND: {CONTRACT_DOC.as_posix()} is not in this checkout")
        return False
    text = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:DIGEST_CHARS]
    status = _header_value(text, "Status")
    dated = _header_value(text, "Date")
    _line("contract in force", f"R001-R015 fictional rulebook v{RULE_VERSION} (pack contract)")
    _line("", f"{CONTRACT_DOC.as_posix()}: {status}, dated {dated}, sha256 {digest}")
    return True


def _header_value(text: str, key: str) -> str:
    """The first word of an ADR header field (``**Status:**``), or ``unstated``.

    Only the leading word is kept: the rest of the line is prose, and a status that is not
    literally stated must not be invented here.
    """
    marker = f"**{key}:**"
    for line in text.splitlines()[:HEADER_LINES]:
        stripped = line.lstrip("> ").strip()
        if not stripped.startswith(marker):
            continue
        remainder = stripped[len(marker) :].strip().replace("**", "").strip()
        word = remainder.split(" ", 1)[0].rstrip(".,;:") if remainder else ""
        return word or "unstated"
    return "unstated"


def _report_catalogue() -> bool:
    """The catalogue the engine and the API would load, and whether it validates."""
    try:
        rules_dir = resolve_rules_dir()
    except RuleDirError as exc:
        _line("rule catalogue", f"NOT FOUND: {_first_line(str(exc))}")
        _line("", f"set {RULES_DIR_ENV} or {PACK_ROOT_ENV} to the catalogue directory")
        return False
    try:
        context = RuleContext.from_rules_dir(rules_dir)
    except (RuleDirError, OSError, ValueError) as exc:
        _line("rule catalogue", f"INVALID at {rules_dir}: {_first_line(str(exc))}")
        return False
    loaded = len(context.rules)
    complete = set(context.rules) == set(RULE_IDS)
    _line("rule catalogue", str(rules_dir))
    _line(
        "",
        f"{loaded} rules, version {RULE_VERSION}, complete={complete} "
        f"({RULE_IDS[0]}..{RULE_IDS[-1]})",
    )
    return complete


def _report_database() -> bool:
    """Whether the review schema is reachable, and which revision it carries."""
    dsn = resolve_dsn()
    safe_dsn = _redact(dsn)
    engine = build_engine(dsn)
    try:
        revision = ReviewStore(engine).schema_revision()
    except Exception as exc:  # noqa: BLE001 - a readiness probe reports, it never raises
        _line("database", f"UNREACHABLE: {type(exc).__name__}: {_first_line(str(exc))}")
        _line("", f"dsn {safe_dsn}")
        return False
    finally:
        # A probe must not leave a pooled connection open: pytest turns the resulting
        # ResourceWarning into an error, and a readiness check that leaks is a bug.
        engine.dispose()
    if revision is None:
        _line("database", "REACHABLE, schema missing: run `uv run alembic upgrade head`")
        _line("", f"dsn {safe_dsn}")
        return False
    _line("database", f"ready, schema revision {revision}")
    _line("", f"dsn {safe_dsn}")
    return True


def _redact(dsn: str) -> str:
    """The DSN with any password replaced — this line is printed, so it must be safe."""
    try:
        return make_url(dsn).render_as_string(hide_password=True)
    except ArgumentError:
        return "<unparseable DSN>"


def _first_line(text: str) -> str:
    """The first line of a multi-line message (the rest is the search path, printed on demand)."""
    return text.splitlines()[0] if text.splitlines() else text


def _line(label: str, value: str) -> None:
    """One aligned ``label  value`` line; an empty label continues the block."""
    print(f"{label:<{LABEL_WIDTH}}{value}".rstrip())
