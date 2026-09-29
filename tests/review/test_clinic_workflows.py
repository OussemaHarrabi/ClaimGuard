"""The four clinic workspaces have live, scoped workflow APIs."""

from __future__ import annotations

import json

import httpx
import pytest
from claimguard.clinic.session import SessionSigner
from claimguard.review.app import create_app
from claimguard.review.store import ReviewStore
from sqlalchemy import Engine, text

from tests.edu import RULES_DIR
from tests.review.conftest import Sandbox, requires_db
from tests.review.test_auth_api import create_test_account, remove_test_account

pytestmark = [pytest.mark.integration, requires_db]


async def _login(client: httpx.AsyncClient, role: str, engine: Engine) -> str:
    user_id, email, password = create_test_account(engine, role)
    response = await client.post(
        "/v1/auth/login",
        json={"tenant_id": "clinic-legacy-demo", "email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return user_id


@pytest.mark.asyncio
async def test_request_escalation_and_clinic_reporting(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    app = create_app(
        store=store,
        rules_dir=RULES_DIR,
        signer=SessionSigner(b"clinic-workflow-tests-session-key-012345"),
    )
    accounts: list[str] = []
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://review.test"
        ) as reviewer:
            accounts.append(await _login(reviewer, "rcm_reviewer", engine))
            submitted = await reviewer.post("/v1/claims", json={"claim": envelope})
            assert submitted.status_code == 201, submitted.text
            run_id = submitted.json()["run"]["run_id"]
            created = await reviewer.post(
                "/v1/requests",
                json={"run_id": run_id, "message": "Please provide the dated coverage letter."},
            )
            assert created.status_code == 201, created.text
            request_id = created.json()["request_id"]
            assert created.json()["status"] == "open"
            assert any(
                item["request_id"] == request_id
                for item in (await reviewer.get("/v1/requests")).json()
            )
            resolved = await reviewer.post(
                f"/v1/requests/{request_id}/resolve",
                json={"response": "Letter received and checked."},
            )
            assert resolved.status_code == 200, resolved.text
            activity = await reviewer.get("/v1/activity")
            assert activity.status_code == 200
            assert any(item["kind"] == "request_resolved" for item in activity.json())
            assert (await reviewer.get("/v1/analytics")).status_code == 403
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://review.test"
        ) as lead:
            accounts.append(await _login(lead, "rcm_lead", engine))
            escalated = await lead.post(
                "/v1/escalations", json={"run_id": run_id, "reason": "Complex coverage exception"}
            )
            assert escalated.status_code == 201, escalated.text
            escalation_id = escalated.json()["escalation_id"]
            assert (
                await lead.post(
                    f"/v1/escalations/{escalation_id}/resolve",
                    json={"resolution": "Reviewed with clinic admin"},
                )
            ).status_code == 200
            quality = await lead.get("/v1/review-quality")
            assert quality.status_code == 200
            assert quality.json()["escalations_resolved"] >= 1
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://review.test"
        ) as admin:
            accounts.append(await _login(admin, "clinic_admin", engine))
            overview = await admin.get("/v1/overview")
            assert overview.status_code == 200
            assert overview.json()["claims"] >= 1
            assert (await admin.get("/v1/analytics")).status_code == 200
            audit = await admin.get("/v1/audit")
            assert audit.status_code == 200
            assert any(item["run_id"] == run_id for item in audit.json())
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """DELETE FROM claimguard.clinic_escalations
                    WHERE run_id IN (SELECT run_id FROM claimguard.rule_runs
                                     WHERE claim_id = :claim_id)"""
                ),
                {"claim_id": envelope["claim_id"]},
            )
            connection.execute(
                text(
                    """DELETE FROM claimguard.clinic_requests
                    WHERE run_id IN (SELECT run_id FROM claimguard.rule_runs
                                     WHERE claim_id = :claim_id)"""
                ),
                {"claim_id": envelope["claim_id"]},
            )
        sandbox.purge()
        for account in accounts:
            remove_test_account(engine, account)


@pytest.mark.asyncio
async def test_intake_and_claim_blind_technical_pages(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    app = create_app(
        store=store,
        rules_dir=RULES_DIR,
        signer=SessionSigner(b"clinic-technical-tests-session-key-01234"),
    )
    accounts: list[str] = []
    job_ids: list[str] = []
    envelope = sandbox.coverage_lapse()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://review.test"
        ) as reviewer:
            accounts.append(await _login(reviewer, "rcm_reviewer", engine))
            created = await reviewer.post(
                "/v1/intake-jobs",
                json={"filename": "claim.json", "content": json.dumps(envelope)},
            )
            assert created.status_code == 201, created.text
            job_id = created.json()["job_id"]
            job_ids.append(job_id)
            assert created.json()["status"] == "needs_review"
            assert (await reviewer.get("/v1/intake-jobs")).status_code == 200
            assert (await reviewer.get(f"/v1/intake-jobs/{job_id}")).status_code == 200
            submitted = await reviewer.post(f"/v1/intake-jobs/{job_id}/submit")
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["run"]["claim_id"] == envelope["claim_id"]
            assert (await reviewer.post(f"/v1/intake-jobs/{job_id}/submit")).status_code == 409
            mine = await reviewer.get("/v1/my-queue")
            assert envelope["claim_id"] in {item["claim_id"] for item in mine.json()["claims"]}
            unexpected = dict(envelope)
            unexpected["patient_note"] = "Sensitive free text must not be stored"
            rejected = await reviewer.post(
                "/v1/intake-jobs",
                json={"filename": "extra.json", "content": json.dumps(unexpected)},
            )
            assert rejected.status_code == 201
            job_ids.append(rejected.json()["job_id"])
            assert rejected.json()["status"] == "rejected"
            stored = await reviewer.get(f"/v1/intake-jobs/{rejected.json()['job_id']}")
            assert stored.json()["draft"] is None
            assert "Sensitive free text" not in stored.text
            assert (await reviewer.get("/v1/operations")).status_code == 403
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://review.test"
        ) as technical:
            accounts.append(await _login(technical, "technical_manager", engine))
            for path in [
                "/v1/intake-jobs/operations",
                "/v1/versions",
                "/v1/redacted-logs",
                "/v1/audit-integrity",
                "/v1/configuration",
            ]:
                response = await technical.get(path)
                assert response.status_code == 200, (path, response.text)
                assert envelope["claim_id"] not in response.text
                assert "claim_id" not in response.text
            assert (await technical.get(f"/v1/intake-jobs/{job_id}")).status_code == 403
            update = await technical.post("/v1/configuration", json={"intake_enabled": False})
            assert update.status_code == 200, update.text
            assert update.json()["intake_enabled"] is False
            await technical.post("/v1/configuration", json={"intake_enabled": True})
    finally:
        for job_id in job_ids:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM claimguard.intake_jobs WHERE job_id = :job_id"),
                    {"job_id": job_id},
                )
        sandbox.purge()
        with engine.begin() as connection:
            connection.execute(
                text(
                    """DELETE FROM claimguard.clinic_configuration
                    WHERE tenant_id = 'clinic-legacy-demo'"""
                )
            )
        for account in accounts:
            remove_test_account(engine, account)
