"""The SQL migration matches the live clinic-directory contract."""

from __future__ import annotations

from pathlib import Path

from claimguard.clinic.access import Role
from claimguard.clinic.directory import CLINICS, DEPARTMENTS, MEMBERSHIPS, USERS
from claimguard.review.store import REQUIRED_TABLES, SCHEMA_REVISION


def test_clinic_directory_migration_has_tables_and_role_guard() -> None:
    migration = (
        Path(__file__).resolve().parents[2]
        / "claimguard/db/migrations/versions/0005_clinic_directory.sql"
    ).read_text(encoding="utf-8")
    credentials = (
        Path(__file__).resolve().parents[2]
        / "claimguard/db/migrations/versions/0007_local_credentials.sql"
    ).read_text(encoding="utf-8")

    assert "-- revision = '0005'" in migration
    assert "-- down_revision = '0004'" in migration
    for table in (CLINICS, USERS, MEMBERSHIPS, DEPARTMENTS):
        assert f"CREATE TABLE claimguard.{table.name}" in migration
        for column in table.columns:
            assert column.name in migration or column.name in credentials
    for role in Role:
        assert role.value in migration
    assert "PRIMARY KEY (tenant_id, user_id)" in migration
    assert "UNIQUE (tenant_id, name)" in migration
    assert SCHEMA_REVISION == "0010"
    assert {table.name for table in (CLINICS, USERS, MEMBERSHIPS, DEPARTMENTS)}.issubset(
        REQUIRED_TABLES
    )


def test_migration_does_not_change_the_frozen_scoring_tables() -> None:
    migration = (
        Path(__file__).resolve().parents[2]
        / "claimguard/db/migrations/versions/0005_clinic_directory.sql"
    ).read_text(encoding="utf-8")

    assert "ALTER TABLE claimguard.rule_results" not in migration
    assert "ALTER TABLE claimguard.rule_runs" not in migration
