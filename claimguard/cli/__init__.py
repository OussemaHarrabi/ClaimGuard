"""The ``claimguard`` operator console.

Four commands, each a thin and honest front for something that already exists:

=================  ==========================================================================
``status``         is this checkout able to run anything, against which contract, on which
                   database revision?
``serve``          the reviewer API (uvicorn, factory ``claimguard.review.app:create_app``)
``evaluate``       the deterministic engine over a mentor-pack split, scored by the mentor's
                   own strict scorer through ``scripts/edu_conformance.py``
``report``         the versioned evaluation report (``scripts/edu_report.py``)
=================  ==========================================================================

Nothing here decides anything about a claim and nothing here re-implements a rule: the console
locates the repository's frozen tooling, runs it with an explicit argv and returns its exit
code, so the command a judge types and the evidence in ``docs/verification/`` come from the
same code path.
"""

from __future__ import annotations
