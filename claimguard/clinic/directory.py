"""Persistent clinic, user and membership directory.

Membership is loaded for each authenticated request, so revocation and role
changes do not wait for an already-issued session to expire.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    MetaData,
    String,
    Table,
    and_,
    func,
    insert,
    select,
    true,
    update,
)
from sqlalchemy.engine import Engine

from claimguard.clinic.access import Principal, Role
from claimguard.clinic.passwords import hash_password, verify_password

DIRECTORY_METADATA = MetaData()

CLINICS = Table(
    "clinics",
    DIRECTORY_METADATA,
    Column("tenant_id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("active", Boolean, nullable=False, server_default=true()),
    schema="claimguard",
)

USERS = Table(
    "users",
    DIRECTORY_METADATA,
    Column("user_id", String, primary_key=True),
    Column("email", String, nullable=False, unique=True),
    Column("password_hash", String),
    Column("display_name", String),
    Column("active", Boolean, nullable=False, server_default=true()),
    schema="claimguard",
)

MEMBERSHIPS = Table(
    "clinic_memberships",
    DIRECTORY_METADATA,
    Column("tenant_id", String, ForeignKey("claimguard.clinics.tenant_id"), primary_key=True),
    Column("user_id", String, ForeignKey("claimguard.users.user_id"), primary_key=True),
    Column("role", String, nullable=False),
    Column("active", Boolean, nullable=False, server_default=true()),
    CheckConstraint(
        "role IN ('rcm_reviewer','rcm_lead','clinic_admin','technical_manager')",
        name="ck_clinic_memberships_role",
    ),
    schema="claimguard",
)

DEPARTMENTS = Table(
    "clinic_departments",
    DIRECTORY_METADATA,
    Column("department_id", String, primary_key=True),
    Column("tenant_id", String, ForeignKey("claimguard.clinics.tenant_id"), nullable=False),
    Column("name", String, nullable=False),
    Column("active", Boolean, nullable=False, server_default=true()),
    schema="claimguard",
)


class ClinicDirectory:
    """Read current role only when user, clinic and membership are active."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def membership(self, user_id: str, tenant_id: str) -> Role | None:
        statement = (
            select(MEMBERSHIPS.c.role)
            .join(USERS, USERS.c.user_id == MEMBERSHIPS.c.user_id)
            .join(CLINICS, CLINICS.c.tenant_id == MEMBERSHIPS.c.tenant_id)
            .where(
                and_(
                    MEMBERSHIPS.c.user_id == user_id,
                    MEMBERSHIPS.c.tenant_id == tenant_id,
                    MEMBERSHIPS.c.active.is_(True),
                    USERS.c.active.is_(True),
                    CLINICS.c.active.is_(True),
                )
            )
        )
        with self._engine.connect() as connection:
            role = connection.execute(statement).scalar_one_or_none()
        return Role(role) if role is not None else None

    def authenticate(self, email: str, password: str, tenant_id: str) -> Principal | None:
        """Check a local credential and active membership for one clinic."""
        statement = (
            select(USERS.c.user_id, USERS.c.password_hash, MEMBERSHIPS.c.role)
            .select_from(USERS)
            .join(MEMBERSHIPS, MEMBERSHIPS.c.user_id == USERS.c.user_id)
            .join(CLINICS, CLINICS.c.tenant_id == MEMBERSHIPS.c.tenant_id)
            .where(
                and_(
                    func.lower(USERS.c.email) == email.strip().lower(),
                    MEMBERSHIPS.c.tenant_id == tenant_id,
                    USERS.c.active.is_(True),
                    MEMBERSHIPS.c.active.is_(True),
                    CLINICS.c.active.is_(True),
                )
            )
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).one_or_none()
        if (
            row is None
            or row.password_hash is None
            or not verify_password(password, str(row.password_hash))
        ):
            return None
        return Principal(user_id=str(row.user_id), tenant_id=tenant_id, role=Role(row.role))

    def team(self, tenant_id: str, *, include_inactive: bool = False) -> list[TeamMember]:
        """List active clinic members without credential or claim fields."""
        statement = (
            select(
                USERS.c.user_id,
                USERS.c.email,
                USERS.c.display_name,
                MEMBERSHIPS.c.role,
                MEMBERSHIPS.c.active,
            )
            .select_from(MEMBERSHIPS)
            .join(USERS, USERS.c.user_id == MEMBERSHIPS.c.user_id)
            .join(CLINICS, CLINICS.c.tenant_id == MEMBERSHIPS.c.tenant_id)
            .where(
                MEMBERSHIPS.c.tenant_id == tenant_id,
                CLINICS.c.active.is_(True),
            )
            .order_by(USERS.c.email)
        )
        if not include_inactive:
            statement = statement.where(MEMBERSHIPS.c.active.is_(True), USERS.c.active.is_(True))
        with self._engine.connect() as connection:
            rows = connection.execute(statement).all()
        return [
            TeamMember(
                user_id=str(row.user_id),
                email=str(row.email),
                display_name=None if row.display_name is None else str(row.display_name),
                role=Role(row.role),
                active=bool(row.active),
            )
            for row in rows
        ]

    def add_member(
        self,
        tenant_id: str,
        *,
        email: str,
        display_name: str | None,
        password: str,
        role: Role,
    ) -> TeamMember:
        """Create a new account in this clinic; never reuse a global email silently."""
        email = email.strip().lower()
        if not email or "@" not in email:
            raise ValueError("a valid email is required")
        if len(password) < 12:
            raise ValueError("password must contain at least 12 characters")
        user_id = f"user-{uuid.uuid4().hex}"
        with self._engine.begin() as connection:
            if connection.execute(
                select(USERS.c.user_id).where(USERS.c.email == email)
            ).scalar_one_or_none():
                raise ValueError("a user with that email already exists")
            if (
                connection.execute(
                    select(CLINICS.c.tenant_id).where(CLINICS.c.tenant_id == tenant_id)
                ).scalar_one_or_none()
                is None
            ):
                raise ValueError("clinic does not exist")
            connection.execute(
                insert(USERS).values(
                    user_id=user_id,
                    email=email,
                    display_name=display_name,
                    password_hash=hash_password(password),
                )
            )
            connection.execute(
                insert(MEMBERSHIPS).values(tenant_id=tenant_id, user_id=user_id, role=role.value)
            )
        return TeamMember(user_id, email, display_name, role, True)

    def set_membership_active(self, tenant_id: str, user_id: str, active: bool) -> TeamMember:
        """Revoke or restore only this clinic membership, not the global user."""
        with self._engine.begin() as connection:
            current_role = connection.execute(
                select(MEMBERSHIPS.c.role).where(
                    MEMBERSHIPS.c.tenant_id == tenant_id, MEMBERSHIPS.c.user_id == user_id
                )
            ).scalar_one_or_none()
            if current_role is None:
                raise ValueError("member not found in this clinic")
            if not active and current_role == Role.CLINIC_ADMIN.value:
                admins = connection.execute(
                    select(func.count())
                    .select_from(MEMBERSHIPS)
                    .where(
                        MEMBERSHIPS.c.tenant_id == tenant_id,
                        MEMBERSHIPS.c.role == Role.CLINIC_ADMIN.value,
                        MEMBERSHIPS.c.active.is_(True),
                    )
                ).scalar_one()
                if admins <= 1:
                    raise ValueError("cannot deactivate the last active clinic admin")
            connection.execute(
                update(MEMBERSHIPS)
                .where(MEMBERSHIPS.c.tenant_id == tenant_id, MEMBERSHIPS.c.user_id == user_id)
                .values(active=active)
            )
        member = next(
            (
                item
                for item in self.team(tenant_id, include_inactive=True)
                if item.user_id == user_id
            ),
            None,
        )
        if member is None:  # pragma: no cover - transaction just confirmed membership
            raise ValueError("member not found in this clinic")
        return member

    def departments(self, tenant_id: str) -> list[Department]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    DEPARTMENTS.c.department_id,
                    DEPARTMENTS.c.name,
                    DEPARTMENTS.c.active,
                )
                .where(DEPARTMENTS.c.tenant_id == tenant_id)
                .order_by(DEPARTMENTS.c.name)
            ).all()
        return [Department(str(row.department_id), str(row.name), bool(row.active)) for row in rows]

    def add_department(self, tenant_id: str, name: str) -> Department:
        name = name.strip()
        if not name:
            raise ValueError("department name must not be blank")
        department_id = f"department-{uuid.uuid4().hex}"
        with self._engine.begin() as connection:
            connection.execute(
                insert(DEPARTMENTS).values(
                    department_id=department_id, tenant_id=tenant_id, name=name
                )
            )
        return Department(department_id, name, True)

    def update_department(
        self, tenant_id: str, department_id: str, *, name: str, active: bool
    ) -> Department:
        name = name.strip()
        if not name:
            raise ValueError("department name must not be blank")
        with self._engine.begin() as connection:
            result = connection.execute(
                update(DEPARTMENTS)
                .where(
                    DEPARTMENTS.c.tenant_id == tenant_id,
                    DEPARTMENTS.c.department_id == department_id,
                )
                .values(name=name, active=active)
            )
            if result.rowcount != 1:
                raise ValueError("department not found in this clinic")
        return Department(department_id, name, active)


@dataclass(frozen=True, slots=True)
class TeamMember:
    user_id: str
    email: str
    display_name: str | None
    role: Role
    active: bool


@dataclass(frozen=True, slots=True)
class Department:
    department_id: str
    name: str
    active: bool
