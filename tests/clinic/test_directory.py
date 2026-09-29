"""Clinic membership is checked against the database on every session read."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from claimguard.clinic.access import Principal, Role
from claimguard.clinic.directory import (
    CLINICS,
    DIRECTORY_METADATA,
    MEMBERSHIPS,
    USERS,
    ClinicDirectory,
)
from claimguard.clinic.passwords import hash_password
from claimguard.clinic.provision import provision_admin
from sqlalchemy import Engine, create_engine, insert, update


@pytest.fixture
def directory_engine() -> Iterator[Engine]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS claimguard")
        DIRECTORY_METADATA.create_all(connection)
    yield engine
    engine.dispose()


def test_membership_is_clinic_scoped_and_revocable(directory_engine: Engine) -> None:
    engine = directory_engine
    with engine.begin() as connection:
        connection.execute(
            insert(CLINICS),
            [{"tenant_id": "clinic-a", "name": "A"}, {"tenant_id": "clinic-b", "name": "B"}],
        )
        connection.execute(insert(USERS).values(user_id="user-1", email="user@example.test"))
        connection.execute(
            insert(MEMBERSHIPS).values(
                tenant_id="clinic-a", user_id="user-1", role=Role.RCM_REVIEWER.value
            )
        )
    directory = ClinicDirectory(engine)

    assert directory.membership("user-1", "clinic-a") is Role.RCM_REVIEWER
    assert directory.membership("user-1", "clinic-b") is None

    with engine.begin() as connection:
        connection.execute(
            update(MEMBERSHIPS)
            .where(MEMBERSHIPS.c.tenant_id == "clinic-a")
            .values(role=Role.RCM_LEAD.value)
        )
    assert directory.membership("user-1", "clinic-a") is Role.RCM_LEAD

    with engine.begin() as connection:
        connection.execute(
            update(MEMBERSHIPS).where(MEMBERSHIPS.c.tenant_id == "clinic-a").values(active=False)
        )
    assert directory.membership("user-1", "clinic-a") is None


def test_inactive_user_or_clinic_cannot_authenticate(directory_engine: Engine) -> None:
    engine = directory_engine
    with engine.begin() as connection:
        connection.execute(insert(CLINICS).values(tenant_id="clinic-a", name="A"))
        connection.execute(insert(USERS).values(user_id="user-1", email="user@example.test"))
        connection.execute(
            insert(MEMBERSHIPS).values(
                tenant_id="clinic-a", user_id="user-1", role=Role.CLINIC_ADMIN.value
            )
        )
        connection.execute(update(USERS).values(active=False))
    directory = ClinicDirectory(engine)
    assert directory.membership("user-1", "clinic-a") is None

    with engine.begin() as connection:
        connection.execute(update(USERS).values(active=True))
        connection.execute(update(CLINICS).values(active=False))
    assert directory.membership("user-1", "clinic-a") is None


def test_authenticate_checks_password_and_current_clinic_membership(
    directory_engine: Engine,
) -> None:
    with directory_engine.begin() as connection:
        connection.execute(insert(CLINICS).values(tenant_id="clinic-a", name="A"))
        connection.execute(
            insert(USERS).values(
                user_id="user-1",
                email="user@example.test",
                password_hash=hash_password("correct horse battery staple"),
            )
        )
        connection.execute(
            insert(MEMBERSHIPS).values(
                tenant_id="clinic-a", user_id="user-1", role=Role.CLINIC_ADMIN.value
            )
        )
    directory = ClinicDirectory(directory_engine)

    assert directory.authenticate(
        "USER@example.test", "correct horse battery staple", "clinic-a"
    ) == Principal(user_id="user-1", tenant_id="clinic-a", role=Role.CLINIC_ADMIN)
    assert directory.authenticate("user@example.test", "wrong", "clinic-a") is None
    assert (
        directory.authenticate("user@example.test", "correct horse battery staple", "clinic-b")
        is None
    )


def test_bootstrap_provisions_one_real_clinic_admin(directory_engine: Engine) -> None:
    principal = provision_admin(
        directory_engine,
        tenant_id="clinic-new",
        clinic_name="North clinic",
        email="admin@north.example",
        password="correct horse battery staple",
    )

    assert principal.role is Role.CLINIC_ADMIN
    assert (
        ClinicDirectory(directory_engine).authenticate(
            "admin@north.example", "correct horse battery staple", "clinic-new"
        )
        == principal
    )
    with pytest.raises(ValueError, match="already exists"):
        provision_admin(
            directory_engine,
            tenant_id="clinic-new",
            clinic_name="North clinic",
            email="admin@north.example",
            password="correct horse battery staple",
        )
