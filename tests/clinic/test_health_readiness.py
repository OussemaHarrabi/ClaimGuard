"""Health cannot claim readiness for an older or incomplete clinic schema."""

from __future__ import annotations

from unittest.mock import Mock

import httpx
import pytest
from claimguard.review.app import create_app
from claimguard.review.store import ReviewStore, SchemaNotMigratedError
from tests.edu import RULES_DIR


@pytest.mark.asyncio
async def test_health_degrades_when_clinic_migration_is_missing() -> None:
    store = Mock(spec=ReviewStore)
    store.schema_revision.return_value = "0004"
    app = create_app(store=store, rules_dir=RULES_DIR)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "schema-missing"


@pytest.mark.asyncio
async def test_health_degrades_when_required_tables_are_missing() -> None:
    store = Mock(spec=ReviewStore)
    store.schema_revision.return_value = "0010"
    store.ensure_schema.side_effect = SchemaNotMigratedError("clinic directory absent")
    app = create_app(store=store, rules_dir=RULES_DIR)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "schema-missing"
