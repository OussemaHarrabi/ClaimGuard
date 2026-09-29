"""Real PostgreSQL checks for clinic ownership of claim runs."""

from __future__ import annotations

import uuid

import pytest
from claimguard.review.store import ReviewStore
from sqlalchemy import Engine, text

from tests.review.conftest import Sandbox, requires_db
from tests.review.test_review_store import submit

pytestmark = [pytest.mark.integration, requires_db]


def test_same_claim_id_is_independent_and_invisible_across_clinics(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    other_clinic = f"clinic-test-{uuid.uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO claimguard.clinics (tenant_id, name) VALUES (:id, 'Test clinic')"),
            {"id": other_clinic},
        )
    try:
        envelope = sandbox.coverage_lapse()
        first_clinic = store.for_tenant("clinic-legacy-demo")
        second_clinic = store.for_tenant(other_clinic)

        first = submit(first_clinic, envelope)
        second = submit(second_clinic, envelope)

        assert first.run.run_id != second.run.run_id
        assert first.run.version == second.run.version == 1
        assert first_clinic.get_run(second.run.run_id) is None
        assert second_clinic.get_run(first.run.run_id) is None
        assert first_clinic.get_claim_envelope(second.run.run_id) is None
        assert second_clinic.get_results(first.run.run_id) == []
        assert {claim.run_id for claim in first_clinic.queue().claims} >= {first.run.run_id}
        assert second.run.run_id not in {claim.run_id for claim in first_clinic.queue().claims}
    finally:
        sandbox.purge()
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM claimguard.clinics WHERE tenant_id = :id"),
                {"id": other_clinic},
            )
