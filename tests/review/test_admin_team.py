"""Clinic admins provision and revoke real clinic accounts."""

from __future__ import annotations

import uuid

import httpx
import pytest
from claimguard.clinic.session import SessionSigner
from claimguard.review.app import create_app
from claimguard.review.store import ReviewStore
from sqlalchemy import Engine, text

from tests.edu import RULES_DIR
from tests.review.conftest import requires_db
from tests.review.test_auth_api import create_test_account, remove_test_account

pytestmark = [pytest.mark.integration, requires_db]


@pytest.mark.asyncio
async def test_admin_creates_and_revokes_a_reviewer(store: ReviewStore, engine: Engine) -> None:
    admin_id, admin_email, admin_password = create_test_account(engine, "clinic_admin")
    created_user: str | None = None
    email = f"new-reviewer-{uuid.uuid4().hex}@example.test"
    app = create_app(
        store=store,
        rules_dir=RULES_DIR,
        signer=SessionSigner(b"test-key-for-admin-team-api-0123456789"),
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://review.test"
        ) as admin:
            login = await admin.post(
                "/v1/auth/login",
                json={
                    "email": admin_email,
                    "password": admin_password,
                    "tenant_id": "clinic-legacy-demo",
                },
            )
            assert login.status_code == 200
            added = await admin.post(
                "/v1/team",
                json={
                    "email": email,
                    "display_name": "New reviewer",
                    "password": "correct horse battery staple",
                    "role": "rcm_reviewer",
                },
            )
            assert added.status_code == 201, added.text
            created_user = added.json()["user_id"]
            assert added.json()["role"] == "rcm_reviewer"
            assert "password" not in added.text
            status = await admin.post(f"/v1/team/{created_user}/status", json={"active": False})
            assert status.status_code == 200, status.text
            assert status.json()["active"] is False
            members = await admin.get("/v1/team?include_inactive=true")
            assert created_user in {member["user_id"] for member in members.json()}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://review.test"
        ) as reviewer:
            denied = await reviewer.post(
                "/v1/auth/login",
                json={
                    "email": email,
                    "password": "correct horse battery staple",
                    "tenant_id": "clinic-legacy-demo",
                },
            )
            assert denied.status_code == 401
    finally:
        if created_user is not None:
            remove_test_account(engine, created_user)
        remove_test_account(engine, admin_id)


@pytest.mark.asyncio
async def test_admin_creates_and_updates_a_department(store: ReviewStore, engine: Engine) -> None:
    admin_id, email, password = create_test_account(engine, "clinic_admin")
    department_id: str | None = None
    app = create_app(
        store=store,
        rules_dir=RULES_DIR,
        signer=SessionSigner(b"test-key-for-admin-departments-0123456789"),
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://review.test"
        ) as admin:
            await admin.post(
                "/v1/auth/login",
                json={"email": email, "password": password, "tenant_id": "clinic-legacy-demo"},
            )
            created = await admin.post(
                "/v1/departments", json={"name": f"Dental-{uuid.uuid4().hex[:8]}"}
            )
            assert created.status_code == 201, created.text
            department_id = created.json()["department_id"]
            listed = await admin.get("/v1/departments")
            assert department_id in {item["department_id"] for item in listed.json()}
            updated = await admin.post(
                f"/v1/departments/{department_id}/update",
                json={"name": "Dental review", "active": False},
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["active"] is False
            assert updated.json()["name"] == "Dental review"
    finally:
        if department_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM claimguard.clinic_departments WHERE department_id = :id"),
                    {"id": department_id},
                )
        remove_test_account(engine, admin_id)
