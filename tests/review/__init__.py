"""Tests for the ClaimGuard reviewer workflow (``claimguard/review``).

Layout and database requirements:

*   ``test_models.py`` — the review contracts and the decision state machine.
    Pure unit tests: no database, always run (CI included).
*   ``test_app_config.py`` — the API's rule-catalogue resolution and its error
    mapping. Pure unit tests.
*   ``test_explanations.py`` — the reviewer layer's use of the bounded
    explanation layer, and the provenance marker the interface shows. Pure unit
    tests (the model path runs against a scripted transport, never a network).
*   ``test_review_store.py`` — persistence and the audit chain.
    **Needs PostgreSQL**: skipped automatically when it is unreachable.
*   ``test_review_api.py`` — the HTTP surface end to end, including the
    explanation provenance served beside the 15 records.
    **Needs PostgreSQL**: skipped automatically when it is unreachable.

The integration modules also need migrations ``0002_review_workflow.sql`` and
``0003_explanation_provenance.sql``; the ``store`` fixture in ``conftest.py``
applies pending migrations itself, so a reachable database is enough.
"""
