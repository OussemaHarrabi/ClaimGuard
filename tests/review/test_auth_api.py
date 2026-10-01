"""Authenticated clinic routes reject absent sessions and claim-blind roles."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from claimguard.clinic.passwords import hash_password
from claimguard.clinic.session import SessionSigner
from claimguard.review.app import create_app
from claimguard.review.explanations import TemplateExplanationProvider
from claimguard.review.store import SCHEMA_REVISION, ReviewStore
from sqlalchemy import Engine, text

from tests.edu import RULES_DIR
from tests.review.conftest import Sandbox, requires_db

pytestmark = [pytest.mark.integration, requires_db]


def create_test_account(engine: Engine, role: str) -> tuple[str, str, str]:
    user_id = f"auth-test-{uuid.uuid4().hex}"
    email = f"{user_id}@example.test"
    password = "correct horse battery staple"
    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO claimguard.users (user_id, email, password_hash)
                VALUES (:user_id, :email, :password_hash)
            """),
            {"user_id": user_id, "email": email, "password_hash": hash_password(password)},
        )
        connection.execute(
            text("""
                INSERT INTO claimguard.clinic_memberships (tenant_id, user_id, role)
                VALUES ('clinic-legacy-demo', :user_id, :role)
            """),
            {"user_id": user_id, "role": role},
        )
    return user_id, email, password


def remove_test_account(engine: Engine, user_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM claimguard.clinic_memberships WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        connection.execute(
            text("DELETE FROM claimguard.users WHERE user_id = :user_id"),
            {"user_id": user_id},
        )


@pytest.mark.asyncio
async def test_claim_routes_require_a_real_clinic_session(store: ReviewStore) -> None:
    app = create_app(
        store=store,
        rules_dir=RULES_DIR,
        explain_provider=TemplateExplanationProvider(),
        signer=SessionSigner(b"test-key-for-clinic-auth-api-0123456789"),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://review.test"
    ) as client:
        response = await client.get("/v1/queue")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_cross_origin_post_is_denied_before_authentication(store: ReviewStore) -> None:
    app = create_app(
        store=store,
        rules_dir=RULES_DIR,
        signer=SessionSigner(b"test-key-for-cross-origin-api-0123456789"),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://review.test"
    ) as client:
        response = await client.post(
            "/v1/auth/login", headers={"origin": "https://attacker.example"}, json={}
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_technical_manager_can_sign_in_but_cannot_read_claims(
    store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    user_id, email, password = create_test_account(engine, "technical_manager")
    envelope: dict[str, Any] = sandbox.coverage_lapse()
    from tests.review.test_review_store import submit

    try:
        run = submit(store, envelope)
        app = create_app(
            store=store,
            rules_dir=RULES_DIR,
            explain_provider=TemplateExplanationProvider(),
            signer=SessionSigner(b"test-key-for-clinic-auth-api-0123456789"),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://review.test"
        ) as client:
            login = await client.post(
                "/v1/auth/login",
                json={"email": email, "password": password, "tenant_id": "clinic-legacy-demo"},
            )
            assert login.status_code == 200
            assert login.json()["role"] == "technical_manager"
            claim = await client.get(f"/v1/runs/{run.run.run_id}/claim")
            assert claim.status_code == 403
            queue = await client.get("/v1/queue")
            assert queue.status_code == 403
            operations = await client.get("/v1/operations")
            assert operations.status_code == 200
            assert operations.json()["schema_revision"] == SCHEMA_REVISION
            assert "claim_id" not in operations.text
    finally:
        sandbox.purge()
        remove_test_account(engine, user_id)
