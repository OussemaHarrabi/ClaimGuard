"""Claim assignments are real tenant-bound database records."""

from __future__ import annotations

import json

import httpx
import pytest
from claimguard.clinic.assignments import AssignmentStore
from claimguard.clinic.session import SessionSigner
from claimguard.review.app import create_app
from claimguard.review.explanations import TemplateExplanationProvider
from claimguard.review.store import ReviewStore
from sqlalchemy import Engine, text

from tests.edu import RULES_DIR
from tests.review.conftest import Sandbox, requires_db
from tests.review.test_auth_api import create_test_account, remove_test_account
from tests.review.test_review_store import submit

pytestmark = [pytest.mark.integration, requires_db]


def test_assignment_drives_a_reviewer_queue_and_rejects_technical_staff(
    engine: Engine, store: ReviewStore, sandbox: Sandbox
) -> None:
    reviewer_id, _, _ = create_test_account(engine, "rcm_reviewer")
    lead_id, _, _ = create_test_account(engine, "rcm_lead")
    technical_id, _, _ = create_test_account(engine, "technical_manager")
    assignments = AssignmentStore(engine)
    claim_id: str | None = None
    try:
        run = submit(store, sandbox.coverage_lapse())
        claim_id = run.run.claim_id
        assigned = assignments.assign(
            "clinic-legacy-demo", run.run.claim_id, reviewer_id, assigned_by=lead_id
        )

        assert assigned.claim_id == run.run.claim_id
        assert assignments.my_claim_ids("clinic-legacy-demo", reviewer_id) == [run.run.claim_id]
        assert assignments.my_claim_ids("another-clinic", reviewer_id) == []
        with pytest.raises(ValueError, match="reviewer"):
            assignments.assign(
                "clinic-legacy-demo", run.run.claim_id, technical_id, assigned_by=lead_id
            )
        with pytest.raises(PermissionError, match="lead or admin"):
            assignments.assign(
                "clinic-legacy-demo", run.run.claim_id, reviewer_id, assigned_by=reviewer_id
            )
    finally:
        if claim_id is not None:
            assignments.unassign("clinic-legacy-demo", claim_id)
        sandbox.purge()
        remove_test_account(engine, reviewer_id)
        remove_test_account(engine, lead_id)
        remove_test_account(engine, technical_id)


@pytest.mark.asyncio
async def test_assignment_api_changes_the_reviewers_my_queue(
    engine: Engine, store: ReviewStore, sandbox: Sandbox
) -> None:
    reviewer_id, reviewer_email, reviewer_password = create_test_account(engine, "rcm_reviewer")
    lead_id, lead_email, lead_password = create_test_account(engine, "rcm_lead")
    assignments = AssignmentStore(engine)
    claim_id: str | None = None
    try:
        run = submit(store, sandbox.coverage_lapse())
        claim_id = run.run.claim_id
        app = create_app(
            store=store,
            rules_dir=RULES_DIR,
            explain_provider=TemplateExplanationProvider(),
            signer=SessionSigner(b"test-key-for-assignments-0123456789"),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://review.test"
        ) as lead:
            await lead.post(
                "/v1/auth/login",
                json={
                    "email": lead_email,
                    "password": lead_password,
                    "tenant_id": "clinic-legacy-demo",
                },
            )
            created = await lead.post(
                "/v1/assignments",
                json={"claim_id": claim_id, "reviewer_user_id": reviewer_id},
            )
            assert created.status_code == 200, created.text
            assert created.json()["assigned_by"] == lead_id
            members = await lead.get("/v1/team")
            assert members.status_code == 200
            assert reviewer_id in {member["user_id"] for member in members.json()}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://review.test"
        ) as reviewer:
            await reviewer.post(
                "/v1/auth/login",
                json={
                    "email": reviewer_email,
                    "password": reviewer_password,
                    "tenant_id": "clinic-legacy-demo",
                },
            )
            mine = await reviewer.get("/v1/my-queue")
            assert mine.status_code == 200, mine.text
            assert claim_id in {claim["claim_id"] for claim in mine.json()["claims"]}
            assert (await reviewer.get("/v1/queue")).status_code == 403
            assert (await reviewer.get("/v1/assignments")).status_code == 403
            assert (await reviewer.get("/v1/team")).status_code == 403
    finally:
        if claim_id is not None:
            assignments.unassign("clinic-legacy-demo", claim_id)
        sandbox.purge()
        remove_test_account(engine, reviewer_id)
        remove_test_account(engine, lead_id)


@pytest.mark.asyncio
async def test_reassignment_revokes_previous_reviewers_claim_access(
    engine: Engine, store: ReviewStore, sandbox: Sandbox
) -> None:
    first_id, first_email, first_password = create_test_account(engine, "rcm_reviewer")
    second_id, second_email, second_password = create_test_account(engine, "rcm_reviewer")
    lead_id, lead_email, lead_password = create_test_account(engine, "rcm_lead")
    envelope = sandbox.coverage_lapse()
    app = create_app(
        store=store,
        rules_dir=RULES_DIR,
        signer=SessionSigner(b"test-key-for-reassignment-access-012345"),
    )
    assignments = AssignmentStore(engine)
    request_id: str | None = None
    job_id: str | None = None
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://review.test"
        ) as first:
            await first.post(
                "/v1/auth/login",
                json={
                    "email": first_email,
                    "password": first_password,
                    "tenant_id": "clinic-legacy-demo",
                },
            )
            submitted = await first.post("/v1/claims", json={"claim": envelope})
            assert submitted.status_code == 201, submitted.text
            run_id = submitted.json()["run"]["run_id"]
            assert (await first.get(f"/v1/runs/{run_id}/claim")).status_code == 200
            intake = await first.post(
                "/v1/intake-jobs",
                json={"filename": "reassigned.json", "content": json.dumps(envelope)},
            )
            assert intake.status_code == 201, intake.text
            job_id = intake.json()["job_id"]
            assert (await first.post(f"/v1/intake-jobs/{job_id}/submit")).status_code == 200
            opened = await first.post(
                "/v1/requests", json={"run_id": run_id, "message": "Need source note"}
            )
            assert opened.status_code == 201, opened.text
            request_id = opened.json()["request_id"]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://review.test"
            ) as lead:
                await lead.post(
                    "/v1/auth/login",
                    json={
                        "email": lead_email,
                        "password": lead_password,
                        "tenant_id": "clinic-legacy-demo",
                    },
                )
                assigned = await lead.post(
                    "/v1/assignments",
                    json={"claim_id": envelope["claim_id"], "reviewer_user_id": second_id},
                )
                assert assigned.status_code == 200, assigned.text
            assert (await first.get(f"/v1/runs/{run_id}/claim")).status_code == 403
            assert (await first.get(f"/v1/runs/{run_id}/results")).status_code == 403
            assert (await first.get(f"/v1/runs/{run_id}/decisions")).status_code == 403
            assert (await first.get(f"/v1/intake-jobs/{job_id}")).status_code == 404
            assert job_id not in {
                job["job_id"] for job in (await first.get("/v1/intake-jobs")).json()
            }
            mine = await first.get("/v1/my-queue")
            assert envelope["claim_id"] not in {row["claim_id"] for row in mine.json()["claims"]}
            activity = await first.get("/v1/activity")
            assert run_id not in {row["run_id"] for row in activity.json()}
            assert request_id not in {
                row["request_id"] for row in (await first.get("/v1/requests")).json()
            }
            denied_resolution = await first.post(
                f"/v1/requests/{request_id}/resolve", json={"response": "Cannot act"}
            )
            assert denied_resolution.status_code == 404
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://review.test"
        ) as second:
            await second.post(
                "/v1/auth/login",
                json={
                    "email": second_email,
                    "password": second_password,
                    "tenant_id": "clinic-legacy-demo",
                },
            )
            assert (await second.get(f"/v1/runs/{run_id}/claim")).status_code == 200
            assert request_id in {
                row["request_id"] for row in (await second.get("/v1/requests")).json()
            }
    finally:
        if job_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM claimguard.intake_jobs WHERE job_id=:id"),
                    {"id": job_id},
                )
        if request_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM claimguard.clinic_requests WHERE request_id=:id"),
                    {"id": request_id},
                )
        assignments.unassign("clinic-legacy-demo", envelope["claim_id"])
        sandbox.purge()
        remove_test_account(engine, first_id)
        remove_test_account(engine, second_id)
        remove_test_account(engine, lead_id)
