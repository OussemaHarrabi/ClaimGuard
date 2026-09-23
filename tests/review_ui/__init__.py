"""Tests for the ClaimGuard reviewer interface (``claimguard/review/ui``).

Layout and requirements:

*   ``test_ui_page.py`` — the page and its assets are served, say what they are,
    and expose nothing else. No database, no browser: always runs.
*   ``test_ui_rendering.py`` — the shipped ``render.mjs`` renders untrusted claim
    text as text, never as markup. No database, no browser: runs the real module
    under Node against a sealed DOM shim (``dom_shim.mjs``), and skips where Node
    is not on PATH.
*   ``test_ui_flow.py`` — the endpoints the page calls: filters and unresolved
    counts, the API's own 422 for a blank actor or reason, and a correction that
    produces a new version while the original stays readable.
    **Needs PostgreSQL**: skipped automatically when it is unreachable.

The interface adds no API endpoint and no dependency: it serves four static files
and speaks to the routes ``claimguard/review/app.py`` already had.
"""
