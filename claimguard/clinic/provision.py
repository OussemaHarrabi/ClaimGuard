"""Explicit first-admin provisioning; no default credentials are installed."""

from __future__ import annotations

import argparse
import getpass
import uuid
from collections.abc import Callable, Sequence

from sqlalchemy import Engine, insert, select

from claimguard.clinic.access import Principal, Role
from claimguard.clinic.directory import CLINICS, MEMBERSHIPS, USERS
from claimguard.clinic.passwords import hash_password


def provision_admin(
    engine: Engine,
    *,
    tenant_id: str,
    clinic_name: str,
    email: str,
    password: str,
) -> Principal:
    """Create an admin for a new or existing clinic, refusing duplicate emails."""
    tenant_id = tenant_id.strip()
    clinic_name = clinic_name.strip()
    email = email.strip().lower()
    if not tenant_id or not clinic_name or not email:
        raise ValueError("clinic ID, clinic name, and email are required")
    if len(password) < 12:
        raise ValueError("admin password must contain at least 12 characters")
    user_id = f"user-{uuid.uuid4().hex}"
    with engine.begin() as connection:
        existing_user = connection.execute(
            select(USERS.c.user_id).where(USERS.c.email == email)
        ).scalar_one_or_none()
        if existing_user is not None:
            raise ValueError("a user with that email already exists")
        existing_clinic = connection.execute(
            select(CLINICS.c.tenant_id).where(CLINICS.c.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if existing_clinic is None:
            connection.execute(insert(CLINICS).values(tenant_id=tenant_id, name=clinic_name))
        connection.execute(
            insert(USERS).values(
                user_id=user_id, email=email, password_hash=hash_password(password)
            )
        )
        connection.execute(
            insert(MEMBERSHIPS).values(
                tenant_id=tenant_id, user_id=user_id, role=Role.CLINIC_ADMIN.value
            )
        )
    return Principal(user_id=user_id, tenant_id=tenant_id, role=Role.CLINIC_ADMIN)


def main(
    argv: Sequence[str] | None = None,
    *,
    engine: Engine | None = None,
    password_reader: Callable[[str], str] = getpass.getpass,
) -> int:
    """Provision the first admin interactively, without echoing the password."""
    parser = argparse.ArgumentParser(description="Provision a ClaimGuard clinic admin")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--clinic-name", required=True)
    parser.add_argument("--email", required=True)
    options = parser.parse_args(argv)
    password = password_reader("New admin password (12+ characters): ")
    owned_engine = engine is None
    if engine is None:
        from claimguard.review.store import build_engine

        engine = build_engine()
    try:
        principal = provision_admin(
            engine,
            tenant_id=options.tenant_id,
            clinic_name=options.clinic_name,
            email=options.email,
            password=password,
        )
    finally:
        if owned_engine:
            engine.dispose()
    print(f"Provisioned clinic admin {principal.user_id} for {principal.tenant_id}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
