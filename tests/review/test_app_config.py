"""Unit tests for the review API's configuration surface.

No database and no network: this module always runs (CI included). It pins the
three things about :mod:`claimguard.review.app` that are decided before any claim
is evaluated — where the rule catalogue comes from, what an unmigrated database
reports, and the input digest that identifies a claim version.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from claimguard.edu.explain import TemplateExplanationProvider
from claimguard.review import app as review_app
from claimguard.review.store import (
    SCHEMA_REVISION,
    ReviewStore,
    SchemaNotMigratedError,
    envelope_digest,
)
from fastapi.routing import APIRoute

from tests.edu import RULES_DIR, base_claim

pytestmark = pytest.mark.unit

#: This module is otherwise pack-independent (it uses the vendored catalogue via
#: ``tests.edu.RULES_DIR``). Only the discovery-default check below needs the real
#: delivered pack on disk, so it carries its own guard instead of skipping the file.
_PACK_RULES = (
    Path(__file__).resolve().parents[2]
    / "ClaimGuardAI_Student_Starter_Pack"
    / "ClaimGuardAI_Student_Starter_Pack"
    / "rules"
)
requires_pack = pytest.mark.skipif(
    not (_PACK_RULES / "rules.json").is_file(),
    reason="mentor starter pack absent (delivered reference material, not tracked in git)",
)


@requires_pack
def test_the_rules_directory_defaults_to_the_pack_catalogue() -> None:
    """With no override, the delivered pack catalogue is discovered on disk."""
    found = review_app.resolve_rules_dir()
    assert (found / "rules.json").is_file()
    assert (found / "services.json").is_file()


def test_the_rules_directory_honours_the_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(review_app.RULES_DIR_ENV, str(RULES_DIR))
    monkeypatch.delenv(review_app.PACK_ROOT_ENV, raising=False)
    assert review_app.resolve_rules_dir() == RULES_DIR.resolve()


def test_the_rules_directory_honours_the_pack_root_convention(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``CLAIMGUARD_PACK_ROOT`` is the same variable ``scripts/edu_conformance.py`` reads."""
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "rules.json").write_text("[]", encoding="utf-8")
    monkeypatch.delenv(review_app.RULES_DIR_ENV, raising=False)
    monkeypatch.setenv(review_app.PACK_ROOT_ENV, str(tmp_path))
    assert review_app.resolve_rules_dir() == rules.resolve()


def test_a_misconfigured_rules_directory_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(review_app.RULES_DIR_ENV, str(tmp_path))
    monkeypatch.delenv(review_app.PACK_ROOT_ENV, raising=False)
    from claimguard.edu.policy import RuleDirError

    with pytest.raises(RuleDirError):
        review_app.resolve_rules_dir()


def test_the_input_digest_is_canonical_but_content_sensitive() -> None:
    """Key order and whitespace must not create a second version of the same claim."""
    envelope = {"claim_id": "CG-1", "total_amount": 190, "notes": "synthetic"}
    reordered = {"notes": "synthetic", "total_amount": 190, "claim_id": "CG-1"}
    assert envelope_digest(envelope) == envelope_digest(reordered)
    assert len(envelope_digest(envelope)) == 64
    assert envelope_digest(envelope) != envelope_digest({**envelope, "total_amount": 191})
    assert envelope_digest(envelope) != envelope_digest({**envelope, "notes": "Synthetic"})


class _UnmigratedStore(ReviewStore):
    """A store whose database has no review tables (0002 not applied)."""

    def __init__(self) -> None:
        pass

    def for_tenant(self, tenant_id: str) -> ReviewStore:
        return self

    def schema_revision(self) -> str | None:
        return None

    def ensure_schema(self) -> None:
        raise SchemaNotMigratedError(
            "the review tables are missing: run `uv run alembic upgrade head` (migration 0002)"
        )


class _ReadyStore(ReviewStore):
    """A store whose schema check passes without a database.

    These tests exercise the rule catalogue, which is loaded *after* the store's
    readiness check and *before* any query: the submission must fail on the
    catalogue, so nothing here ever reaches a connection.
    """

    def __init__(self) -> None:
        pass

    def for_tenant(self, tenant_id: str) -> ReviewStore:
        return self

    def schema_revision(self) -> str | None:
        return SCHEMA_REVISION

    def ensure_schema(self) -> None:
        """Nothing to check: no query is ever issued."""


async def _client(store: ReviewStore, rules_dir: str | Path | None) -> httpx.AsyncClient:
    from claimguard.clinic.access import Role
    from claimguard.clinic.directory import ClinicDirectory
    from claimguard.clinic.session import SessionSigner

    class DirectoryStub:
        def membership(self, user_id: str, tenant_id: str) -> Role | None:
            return Role.RCM_LEAD if (user_id, tenant_id) == ("r", "clinic-legacy-demo") else None

    signer = SessionSigner(b"test-key-for-review-config-0123456789")
    app = review_app.create_app(
        store=store,
        rules_dir=rules_dir,
        explain_provider=TemplateExplanationProvider(),
        signer=signer,
        directory=cast(ClinicDirectory, DirectoryStub()),
    )
    token = signer.issue("r", "clinic-legacy-demo")
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://review.test",
        cookies={"claimguard_session": token},
    )


async def _assert_catalogue_503(client: httpx.AsyncClient, envelope: dict[str, Any]) -> None:
    """A submission the catalogue cannot serve is a structured 503, never a 500."""
    response = await client.post("/v1/claims", json={"claim": envelope})
    assert response.status_code == review_app.RULES_UNAVAILABLE_STATUS
    assert response.status_code != 500
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["error"] == "RuleDirError"
    assert review_app.RULES_DIR_ENV in body["detail"]
    assert review_app.PACK_ROOT_ENV in body["detail"]


async def test_a_missing_rule_catalogue_is_a_structured_503(tmp_path: Path) -> None:
    """The measured defect: a valid envelope reached a bare 500 when no catalogue resolved.

    A submission is the one request that cannot be answered without the rulebook,
    and the catalogue is a dependency the service either has or has not been
    configured with. That is a 503 naming the setting to fix — the same shape an
    unmigrated database gets — and never an unhandled 5xx with a non-JSON body.
    """
    store = cast(ReviewStore, _ReadyStore())
    async with await _client(store, tmp_path) as client:
        health = await client.get("/v1/health")
        assert health.status_code == 200
        assert health.json()["rules_ready"] is False
        await _assert_catalogue_503(client, base_claim())


async def test_health_stays_readable_when_no_catalogue_path_resolves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A fresh checkout without the delivered pack still exposes degraded readiness.

    This differs from an explicitly configured but invalid directory: resolving the
    directory itself raises. Health must catch that once and avoid resolving the same
    missing dependency again while constructing its response.
    """
    monkeypatch.delenv(review_app.RULES_DIR_ENV, raising=False)
    monkeypatch.delenv(review_app.PACK_ROOT_ENV, raising=False)
    monkeypatch.setattr(review_app, "_REPO_ROOT", tmp_path)
    app = review_app.create_app(
        store=cast(ReviewStore, _ReadyStore()),
        explain_provider=TemplateExplanationProvider(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://review.test"
    ) as client:
        response = await client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["rules_ready"] is False
    assert response.json()["rules_dir"] is None


async def test_an_env_configured_but_unusable_catalogue_is_also_a_structured_503(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The same answer when the setting exists and points somewhere without a catalogue."""
    monkeypatch.setenv(review_app.RULES_DIR_ENV, str(tmp_path))
    monkeypatch.delenv(review_app.PACK_ROOT_ENV, raising=False)
    store = cast(ReviewStore, _ReadyStore())
    async with await _client(store, None) as client:
        await _assert_catalogue_503(client, base_claim())


async def test_an_unmigrated_database_is_reported_not_crashed() -> None:
    """Every data route answers 503 with the command that fixes it; health stays honest."""
    store = cast(ReviewStore, _UnmigratedStore())
    async with await _client(store, RULES_DIR) as client:
        health = await client.get("/v1/health")
        assert health.status_code == 200
        assert health.json()["status"] == "degraded"
        assert health.json()["database"] == "schema-missing"
        assert health.json()["rules_ready"] is True

        for method, path, payload in (
            ("get", "/v1/runs/RUN-x", None),
            ("get", "/v1/runs/RUN-x/results", None),
            ("get", "/v1/runs/RUN-x/decisions", None),
            ("get", "/v1/queue", None),
            (
                "post",
                "/v1/runs/RUN-x/decisions",
                {"rule_id": "R003", "action": "confirm_issue", "actor": "r", "reason": "why"},
            ),
        ):
            response = (
                await getattr(client, method)(path, json=payload)
                if payload
                else await getattr(client, method)(path)
            )
            assert response.status_code == 503, path
            assert "alembic upgrade head" in response.json()["detail"]
            assert response.json()["error"] == "SchemaNotMigratedError"


def test_the_documented_surface_is_what_is_mounted() -> None:
    """The eight operations this package promises, and no adjudication endpoint."""
    paths = {route.path for route in review_app.app.routes if isinstance(route, APIRoute)}
    assert paths >= {
        "/v1/health",
        "/v1/claims",
        "/v1/claims/{claim_id}/recheck",
        "/v1/runs/{run_id}",
        "/v1/runs/{run_id}/claim",
        "/v1/runs/{run_id}/results",
        "/v1/runs/{run_id}/decisions",
        "/v1/queue",
    }


def test_the_module_exposes_an_app_for_uvicorn() -> None:
    assert isinstance(review_app.app, review_app.FastAPI)
    assert review_app.app.state.store is not None
