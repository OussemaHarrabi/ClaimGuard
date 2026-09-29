"""Authority boundaries for clinic-scoped workspaces."""

from __future__ import annotations

import pytest
from claimguard.clinic.access import Action, Principal, Role, authorize


def test_rcm_reviewer_can_review_only_inside_own_clinic() -> None:
    reviewer = Principal(user_id="user-1", tenant_id="clinic-a", role=Role.RCM_REVIEWER)

    authorize(reviewer, Action.READ_CLAIM, tenant_id="clinic-a")
    authorize(reviewer, Action.RECORD_DECISION, tenant_id="clinic-a")

    with pytest.raises(PermissionError, match="clinic"):
        authorize(reviewer, Action.READ_CLAIM, tenant_id="clinic-b")


def test_technical_manager_cannot_read_claim_contents() -> None:
    technician = Principal(user_id="tech-1", tenant_id="clinic-a", role=Role.TECHNICAL_MANAGER)

    authorize(technician, Action.READ_OPERATIONS, tenant_id="clinic-a")
    with pytest.raises(PermissionError, match="permission"):
        authorize(technician, Action.READ_CLAIM, tenant_id="clinic-a")


def test_clinic_admin_can_assign_but_reviewer_cannot() -> None:
    admin = Principal(user_id="admin-1", tenant_id="clinic-a", role=Role.CLINIC_ADMIN)
    reviewer = Principal(user_id="user-1", tenant_id="clinic-a", role=Role.RCM_REVIEWER)

    authorize(admin, Action.ASSIGN_CLAIM, tenant_id="clinic-a")
    with pytest.raises(PermissionError, match="permission"):
        authorize(reviewer, Action.ASSIGN_CLAIM, tenant_id="clinic-a")


def test_identity_fields_cannot_be_blank() -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        Principal(user_id="user-1", tenant_id=" ", role=Role.RCM_REVIEWER)
