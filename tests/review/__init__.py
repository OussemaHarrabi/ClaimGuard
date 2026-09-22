"""Tests for the ClaimGuard reviewer workflow (``claimguard/review``).

Layout and database requirements:

*   ``test_models.py`` — the review contracts and the decision state machine.
    Pure unit tests: no database, always run (CI included).
*   ``test_app_config.py`` — the API's rule-catalogue resolution. Pure unit tests.
*   ``test_review_store.py`` — persistence and the audit chain.
    **Needs PostgreSQL**: skipped automatically when it is unreachable.
*   ``test_review_api.py`` — the HTTP surface end to end.
    **Needs PostgreSQL**: skipped automatically when it is unreachable.

The integration modules also need migration ``0002_review_workflow.sql``; the
``store`` fixture in ``conftest.py`` applies pending migrations itself, so a
reachable database is enough.
"""
