"""Fixtures for the reviewer-interface tests.

DATABASE POLICY
---------------
The page and its assets are served from disk, so ``test_ui_page.py`` and
``test_ui_rendering.py`` need neither a database nor a browser and always run:
they use ``ui_client``, an app whose store is never touched by a request for the
page. ``test_ui_flow.py`` drives the endpoints the page calls and carries
``requires_db``, exactly as ``tests/review/test_review_api.py`` does.

The database fixtures are **reused from** ``tests/review/conftest.py`` rather than
copied: ``engine``, ``store``, ``sandbox`` and ``client`` are imported into this
module so pytest sees them here too (fixture lookup walks the requesting test's
own conftest chain, so an imported fixture is only visible once it is bound in
this namespace). That keeps migration handling and row cleanup in one place.

NODE POLICY
-----------
The rendering tests run the shipped ``render.mjs`` under Node — no browser, no
npm package, no dependency added to the project. ``requires_node`` skips them
where Node is not installed.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final

import httpx
import pytest
from claimguard.review.app import create_app

from tests.edu import RULES_DIR

# Re-exported so pytest finds them in this test package's conftest chain: the
# database machinery (migrations, row cleanup) stays owned by tests/review.
from tests.review.conftest import client, engine, sandbox, store

#: The fixtures this conftest binds for ``tests/review_ui`` (see the note above).
__all__ = ["client", "engine", "sandbox", "store"]

#: This directory: where the harness and the DOM shim live.
HERE: Final[Path] = Path(__file__).resolve().parent

#: The Node harness that runs ``render.mjs`` over a payload, and its DOM shim.
HARNESS: Final[Path] = HERE / "render_harness.mjs"
DOM_SHIM: Final[Path] = HERE / "dom_shim.mjs"

#: The Node executable, or None where Node is not installed.
NODE: Final[str | None] = shutil.which("node")

requires_node = pytest.mark.skipif(
    NODE is None,
    reason="Node is not on PATH; the render tests run the shipped JavaScript with it",
)


def run_node(*args: str) -> str:
    """Run Node with ``args`` and return stdout, failing the test on any error."""
    assert NODE is not None  # guaranteed by requires_node on every caller
    completed = subprocess.run(  # noqa: S603 - a fixed argv, no shell, no caller input
        [NODE, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


@pytest.fixture
async def ui_client() -> AsyncIterator[httpx.AsyncClient]:
    """The app that serves the page. No request here reaches the database."""
    app = create_app(rules_dir=RULES_DIR)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://review.test") as http:
        yield http
