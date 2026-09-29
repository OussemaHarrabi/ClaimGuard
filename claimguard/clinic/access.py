"""Explicit clinic-scoped permissions; UI visibility is never authorization."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class Role(StrEnum):
    RCM_REVIEWER = "rcm_reviewer"
    RCM_LEAD = "rcm_lead"
    CLINIC_ADMIN = "clinic_admin"
    TECHNICAL_MANAGER = "technical_manager"


class Action(StrEnum):
    READ_CLAIM = "read_claim"
    CREATE_CLAIM = "create_claim"
    RECORD_DECISION = "record_decision"
    RECHECK_CLAIM = "recheck_claim"
    READ_QUEUE = "read_queue"
    ASSIGN_CLAIM = "assign_claim"
    READ_ANALYTICS = "read_analytics"
    MANAGE_TEAM = "manage_team"
    READ_AUDIT = "read_audit"
    READ_OPERATIONS = "read_operations"
    MANAGE_OPERATIONS = "manage_operations"


_REVIEW: Final[frozenset[Action]] = frozenset(
    {
        Action.READ_CLAIM,
        Action.CREATE_CLAIM,
        Action.RECORD_DECISION,
        Action.RECHECK_CLAIM,
        Action.READ_QUEUE,
    }
)

PERMISSIONS: Final[dict[Role, frozenset[Action]]] = {
    Role.RCM_REVIEWER: _REVIEW,
    Role.RCM_LEAD: _REVIEW | {Action.ASSIGN_CLAIM, Action.READ_ANALYTICS, Action.READ_AUDIT},
    Role.CLINIC_ADMIN: frozenset(Action),
    Role.TECHNICAL_MANAGER: frozenset({Action.READ_OPERATIONS, Action.MANAGE_OPERATIONS}),
}


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    tenant_id: str
    role: Role

    def __post_init__(self) -> None:
        for name in ("user_id", "tenant_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be blank")


def authorize(principal: Principal, action: Action, *, tenant_id: str) -> None:
    """Fail closed before accessing a clinic resource."""
    if principal.tenant_id != tenant_id:
        raise PermissionError("resource belongs to another clinic")
    if action not in PERMISSIONS[principal.role]:
        raise PermissionError(f"role {principal.role.value} lacks permission {action.value}")
