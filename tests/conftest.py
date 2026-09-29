"""Shared pytest configuration for the ClaimGuard test suite.

WHY THIS FILE EXISTS
--------------------
Several tests exercise the repository's scripts the way an operator does — by
running them as child processes (the conformance harness, the AI ablation
script, the report generator, the intake scripts) — and then decode the child's
stdout as UTF-8.

A child process does not write UTF-8 by default: it uses the locale/console code
page. On Windows that means the em-dash in the ablation summary
("RESULT: PASS — the assistance layer moved no status on either path") is
written as the single byte ``0x97``, which is not valid UTF-8. The parent then
fails while decoding, in a reader thread, so the test fails — or errors at
teardown — for a reason that has nothing to do with the code under test.

Enabling Python's UTF-8 mode here fixes every such call site at once: the
setting lives in ``os.environ`` before any test runs, and every child process
inherits it. Without this, each of the seven subprocess helpers would have to
repeat the same environment setup, and any new one would silently reintroduce
the bug the first time a script prints a non-ASCII character.
"""

from __future__ import annotations

import os

# ``setdefault`` so an operator who has deliberately chosen a different value
# keeps it; the suite is verified to pass under UTF-8 mode.
os.environ.setdefault("PYTHONUTF8", "1")
