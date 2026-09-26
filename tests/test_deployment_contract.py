"""Deployment contracts that are easy to regress without executing containers."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]


def test_container_healthchecks_reject_a_degraded_readiness_body() -> None:
    """HTTP 200 is only transport health; the JSON verdict owns readiness."""
    for relative in ("Dockerfile", "docker-compose.yml"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "body.get('status') == 'ok'" in text, relative


def test_compose_builds_the_next_reviewer_against_the_api_service() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "context: ./frontend" in compose
    assert "CLAIMGUARD_API_ORIGIN: http://api:8000" in compose
    assert '"3001:3000"' in compose
    assert "/app/.next/standalone" in frontend
    assert 'CMD ["node", "server.js"]' in frontend


def test_root_docker_context_excludes_secrets_and_build_artifacts() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for entry in (
        ".git",
        ".env",
        ".env.*",
        ".venv",
        "ClaimGuardAI_Student_Starter_Pack",
        "frontend/node_modules",
        "frontend/.next",
    ):
        assert entry in dockerignore
