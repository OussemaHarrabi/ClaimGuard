"""Clinic-scoped reviewer assignments backed by PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    Table,
    and_,
    delete,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection, Engine

from claimguard.clinic.access import Role
from claimguard.clinic.directory import CLINICS, MEMBERSHIPS, USERS
from claimguard.review.store import RUNS

ASSIGNMENT_METADATA = MetaData()
ASSIGNMENTS = Table(
    "claim_assignments",
    ASSIGNMENT_METADATA,
    Column("tenant_id", String, ForeignKey("claimguard.clinics.tenant_id"), primary_key=True),
    Column("claim_id", String, primary_key=True),
    Column("reviewer_user_id", String, ForeignKey("claimguard.users.user_id"), nullable=False),
    Column("assigned_by", String, ForeignKey("claimguard.users.user_id"), nullable=False),
    Column("assigned_at", DateTime(timezone=True), nullable=False),
    schema="claimguard",
)


@dataclass(frozen=True, slots=True)
class Assignment:
    tenant_id: str
    claim_id: str
    reviewer_user_id: str
    assigned_by: str


def _active_role(connection: Connection, tenant_id: str, user_id: str) -> Role | None:
    role = connection.execute(
        select(MEMBERSHIPS.c.role)
        .join(USERS, USERS.c.user_id == MEMBERSHIPS.c.user_id)
        .join(CLINICS, CLINICS.c.tenant_id == MEMBERSHIPS.c.tenant_id)
        .where(
            MEMBERSHIPS.c.tenant_id == tenant_id,
            MEMBERSHIPS.c.user_id == user_id,
            MEMBERSHIPS.c.active.is_(True),
            USERS.c.active.is_(True),
            CLINICS.c.active.is_(True),
        )
    ).scalar_one_or_none()
    return Role(role) if role is not None else None


class AssignmentStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def assign(
        self, tenant_id: str, claim_id: str, reviewer_user_id: str, *, assigned_by: str
    ) -> Assignment:
        """Assign an existing clinic claim to an active reviewer or lead."""
        with self._engine.begin() as connection:
            actor_role = _active_role(connection, tenant_id, assigned_by)
            if actor_role not in {Role.RCM_LEAD, Role.CLINIC_ADMIN}:
                raise PermissionError("assignment requires an active lead or admin")
            reviewer_role = _active_role(connection, tenant_id, reviewer_user_id)
            if reviewer_role not in {Role.RCM_REVIEWER, Role.RCM_LEAD}:
                raise ValueError("assignee must be an active clinic reviewer or lead")
            run_id = connection.execute(
                select(RUNS.c.run_id)
                .where(RUNS.c.tenant_id == tenant_id, RUNS.c.claim_id == claim_id)
                .limit(1)
            ).scalar_one_or_none()
            if run_id is None:
                raise ValueError("claim does not exist in this clinic")
            statement = insert(ASSIGNMENTS).values(
                tenant_id=tenant_id,
                claim_id=claim_id,
                reviewer_user_id=reviewer_user_id,
                assigned_by=assigned_by,
                assigned_at=func.now(),
            )
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[ASSIGNMENTS.c.tenant_id, ASSIGNMENTS.c.claim_id],
                    set_={
                        "reviewer_user_id": reviewer_user_id,
                        "assigned_by": assigned_by,
                        "assigned_at": func.now(),
                    },
                )
            )
        return Assignment(tenant_id, claim_id, reviewer_user_id, assigned_by)

    def claim_for_intake(self, tenant_id: str, claim_id: str, reviewer_user_id: str) -> bool:
        """Let whoever intook an unassigned claim review it. Returns whether it was claimed.

        WHY THIS IS NOT `assign` AND TAKES NO `assigned_by`
        --------------------------------------------------
        Assignment is a lead's or an admin's act: `assign` refuses anyone else, which is the point
        of it. Intake is a reviewer's act that happens to create work, and a reviewer cannot
        delegate to themselves through that door. So this is a separate, narrower write - and the
        narrowness IS the safeguard:

        * it never displaces an existing assignment, so intake never takes work from a reviewer a
          lead already gave it to, and a later reassignment still removes the intaker's access;
        * it still refuses a claim that is not in this clinic, and refuses to hand it to anyone
          who is not an active reviewer or lead;
        * `assigned_by` is the intaker themselves, because that is who decided the work is theirs.

        It exists because of de-duplication. `record_run` keys on the submitted content, so a
        package whose claim was already checked resolves to the run that already exists and
        `initiated_by` names its first submitter. The intaker would otherwise be handed a run id
        they cannot open, and their own package would vanish from their intake list.
        """
        with self._engine.begin() as connection:
            role = _active_role(connection, tenant_id, reviewer_user_id)
            if role not in {Role.RCM_REVIEWER, Role.RCM_LEAD}:
                return False
            exists = connection.execute(
                select(RUNS.c.run_id)
                .where(RUNS.c.tenant_id == tenant_id, RUNS.c.claim_id == claim_id)
                .limit(1)
            ).scalar_one_or_none()
            if exists is None:
                return False
            claimed = connection.execute(
                insert(ASSIGNMENTS)
                .values(
                    tenant_id=tenant_id,
                    claim_id=claim_id,
                    reviewer_user_id=reviewer_user_id,
                    assigned_by=reviewer_user_id,
                    assigned_at=func.now(),
                )
                .on_conflict_do_nothing(
                    index_elements=[ASSIGNMENTS.c.tenant_id, ASSIGNMENTS.c.claim_id]
                )
                .returning(ASSIGNMENTS.c.claim_id)
            ).scalar_one_or_none()
        return claimed is not None

    def my_claim_ids(self, tenant_id: str, user_id: str) -> list[str]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(ASSIGNMENTS.c.claim_id).where(
                    ASSIGNMENTS.c.tenant_id == tenant_id,
                    ASSIGNMENTS.c.reviewer_user_id == user_id,
                )
            ).all()
        return [str(row.claim_id) for row in rows]

    def visible_claim_ids(self, tenant_id: str, user_id: str) -> list[str]:
        """Assigned claims, plus the user's own submissions only while unassigned."""
        join = RUNS.outerjoin(
            ASSIGNMENTS,
            and_(
                ASSIGNMENTS.c.tenant_id == RUNS.c.tenant_id,
                ASSIGNMENTS.c.claim_id == RUNS.c.claim_id,
            ),
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(RUNS.c.claim_id)
                .select_from(join)
                .where(
                    RUNS.c.tenant_id == tenant_id,
                    or_(
                        ASSIGNMENTS.c.reviewer_user_id == user_id,
                        and_(
                            ASSIGNMENTS.c.claim_id.is_(None),
                            RUNS.c.initiated_by == user_id,
                        ),
                    ),
                )
                .distinct()
            ).all()
        return [str(row.claim_id) for row in rows]

    def can_review(self, tenant_id: str, claim_id: str, user_id: str) -> bool:
        return claim_id in self.visible_claim_ids(tenant_id, user_id)

    def list_assignments(self, tenant_id: str) -> list[Assignment]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    ASSIGNMENTS.c.tenant_id,
                    ASSIGNMENTS.c.claim_id,
                    ASSIGNMENTS.c.reviewer_user_id,
                    ASSIGNMENTS.c.assigned_by,
                ).where(ASSIGNMENTS.c.tenant_id == tenant_id)
            ).all()
        return [Assignment(*map(str, row)) for row in rows]

    def unassign(self, tenant_id: str, claim_id: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                delete(ASSIGNMENTS).where(
                    ASSIGNMENTS.c.tenant_id == tenant_id,
                    ASSIGNMENTS.c.claim_id == claim_id,
                )
            )
