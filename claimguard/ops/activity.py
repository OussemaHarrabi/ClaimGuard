"""Role-aware, claim-blind activity tracing for the operations console (P2).

WHY THIS EXISTS
---------------
The operations console can already show platform health, metrics, traces and the
audit verdict, but a Technical Manager cannot answer the first debugging
question: *who did what, where, and when — across every role*. This module adds
that view without opening a claim: it projects the three actor-bearing tables the
schema actually has into one bounded timeline, resolves the actor's role from the
clinic directory, and counts each role's recent activity.

THE BOUNDARY THIS MODULE KEEPS
------------------------------
*   **No claim content.** Every field below is an opaque reference, a role, a
    display actor (email or user id), an area and a bounded status string. No
    envelope, no claim id, no member/patient identifier and no free text ever
    leaves this module. ``reference`` is an opaque run/job/decision id only.
*   **Real actors only.** ``claimguard.audit_events`` has no actor column, so it
    is deliberately absent: only the three tables that record who acted are
    read.
*   **Tenant from the session, never a parameter.** The clinic is taken from the
    resolved principal; there is no ``tenant`` query parameter to spoof.
*   **Fail-open, bounded, never a 500.** A database that cannot answer degrades
    to a normal ``200`` with the source marked ``unavailable``. Queries are
    capped by :data:`MAX_ACTIVITY_LIMIT` and carry a short per-statement
    timeout.

THE WINDOW
----------
:data:`ACTIVITY_WINDOW_DAYS` (7 days by default) is the one recency window
shared by the activity source's freshness verdict and the per-role
``recent_actions`` count. It is a module constant so both surfaces cannot drift;
:func:`build_activity` and :func:`build_roles` read the same value.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final, Literal, cast

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from claimguard.clinic.access import Principal, Role
from claimguard.config import get_settings
from claimguard.ops.operations import require_operations
from claimguard.ops.sources import SourceState, SourceStatus

logger = logging.getLogger(__name__)

#: The recency window, in days, shared by the activity freshness verdict and the
#: per-role ``recent_actions`` count. One constant so the two cannot drift.
ACTIVITY_WINDOW_DAYS: Final = 7

#: Short per-statement timeout (milliseconds) for the activity projections. A
#: slow directory or a growth spurt degrades the response instead of holding a
#: connection.
ACTIVITY_STATEMENT_TIMEOUT_MS: Final = 1500

#: The activity page default and hard maximum.
DEFAULT_ACTIVITY_LIMIT: Final = 50
MAX_ACTIVITY_LIMIT: Final = 200

#: ``app.state`` override attributes, injectable so tests never touch settings.
_WINDOW_DAYS_ATTR: Final = "activity_window_days"
_STATEMENT_TIMEOUT_ATTR: Final = "activity_statement_timeout_ms"
_ENGINE_ATTR: Final = "activity_engine"

#: The bounded set of areas the timeline exposes. Audit events are excluded: the
#: ledger has no actor column and an entry without an actor would be a lie.
Area = Literal["claim_submission", "review_decision", "intake"]

Action = Literal["claim_submitted", "decision_recorded", "document_ingested"]

_ROLE_ORDER: Final[tuple[Role, ...]] = tuple(Role)
_VALID_AREAS: Final[frozenset[str]] = frozenset({"claim_submission", "review_decision", "intake"})

#: The one UNION of actor-bearing rows. Each branch names its real actor column
#: and its own outcome; audit_events is absent on purpose (it has no actor).
_EVENTS_UNION: Final = """
WITH events AS (
    SELECT rr.created_at AS at,
           rr.tenant_id AS tenant_id,
           rr.initiated_by AS actor,
           'claim_submission'::text AS area,
           'claim_submitted'::text AS action,
           CASE WHEN rr.supersedes_run_id IS NULL THEN 'initial' ELSE 'recheck' END AS outcome,
           rr.run_id AS reference
      FROM claimguard.rule_runs AS rr
    UNION ALL
    SELECT rd.created_at,
           rd.tenant_id,
           rd.actor,
           'review_decision'::text,
           'decision_recorded'::text,
           rd.action,
           rd.decision_id::text
      FROM claimguard.review_decisions AS rd
    UNION ALL
    SELECT ij.created_at,
           ij.tenant_id,
           ij.submitted_by,
           'intake'::text,
           'document_ingested'::text,
           ij.status,
           ij.job_id::text
      FROM claimguard.intake_jobs AS ij
)
"""

#: Bounded, windowed page of entries with the actor's role and display name.
_ACTIVITY_SQL: Final = (
    _EVENTS_UNION
    + """
SELECT events.at,
       members.role AS role,
       COALESCE(users.email, events.actor) AS actor,
       events.area,
       events.action,
       events.outcome,
       events.reference
  FROM events
  LEFT JOIN claimguard.clinic_memberships AS members
         ON members.tenant_id = events.tenant_id AND members.user_id = events.actor
  LEFT JOIN claimguard.users AS users ON users.user_id = events.actor
 WHERE events.tenant_id = :tenant
   AND events.at >= :cutoff
   AND (CAST(:role AS text) IS NULL OR members.role = CAST(:role AS text))
   AND (CAST(:area AS text) IS NULL OR events.area = CAST(:area AS text))
 ORDER BY events.at DESC
 LIMIT :limit
"""
)

#: The newest activity overall, for the honest healthy/stale/unknown verdict.
_LATEST_SQL: Final = (
    _EVENTS_UNION
    + """
SELECT max(at) AS latest_at FROM events WHERE events.tenant_id = :tenant
"""
)

#: Per-role totals over the shared window; ``areas`` is the role's evidence.
_ROLES_SQL: Final = (
    _EVENTS_UNION
    + """
SELECT members.role AS role,
       count(*) FILTER (WHERE events.at >= :cutoff) AS recent_actions,
       max(events.at) AS last_active_at,
       array_agg(DISTINCT events.area) AS areas
  FROM events
  JOIN claimguard.clinic_memberships AS members
    ON members.tenant_id = events.tenant_id AND members.user_id = events.actor
 WHERE events.tenant_id = :tenant
 GROUP BY members.role
"""
)

#: Active memberships with their display email, one row per member.
_MEMBERS_SQL: Final = """
SELECT members.role AS role, users.email AS email
  FROM claimguard.clinic_memberships AS members
  JOIN claimguard.users AS users ON users.user_id = members.user_id
  JOIN claimguard.clinics AS clinics ON clinics.tenant_id = members.tenant_id
 WHERE members.tenant_id = :tenant
   AND members.active IS TRUE
   AND users.active IS TRUE
   AND clinics.active IS TRUE
 ORDER BY members.role, users.email
"""


# ---------------------------------------------------------------------------
# Response contracts
# ---------------------------------------------------------------------------


class ActivityEntry(BaseModel):
    """One real action by one actor, claim-blind."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    at: datetime
    role: Role | None = None
    actor: str
    area: Area
    action: Action
    outcome: str
    reference: str


class ActivityResponse(BaseModel):
    """One bounded, filtered page of the platform's activity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: SourceStatus
    role: Role | None = None
    area: Area | None = None
    limit: int
    entries: list[ActivityEntry]


class RoleSummary(BaseModel):
    """One role's active membership and its bounded recent activity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Role
    active_members: int
    members: list[str]
    recent_actions: int
    areas: list[Area]
    last_active_at: datetime | None = None


class RolesResponse(BaseModel):
    """Every role with an active membership in the tenant, with real counts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    checked_at: datetime
    roles: list[RoleSummary]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


router = APIRouter(
    prefix="/v1/operations",
    tags=["operations"],
    dependencies=[Depends(require_operations)],
)


@router.get("/activity", response_model=ActivityResponse)
def activity(
    request: Request,
    role: Annotated[Role | None, Query()] = None,
    area: Annotated[Area | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_ACTIVITY_LIMIT)] = DEFAULT_ACTIVITY_LIMIT,
) -> ActivityResponse:
    """Who did what, anywhere in the platform, for this clinic only."""
    principal = cast(Principal, request.state.principal)
    return build_activity(
        request.app,
        tenant_id=principal.tenant_id,
        role=role,
        area=area,
        limit=limit,
    )


@router.get("/roles", response_model=RolesResponse)
def roles(request: Request) -> RolesResponse:
    """Every active role in this clinic, with real membership and activity counts."""
    principal = cast(Principal, request.state.principal)
    return build_roles(request.app, tenant_id=principal.tenant_id)


# ---------------------------------------------------------------------------
# Handlers (module-level so they are directly callable and typed)
# ---------------------------------------------------------------------------


def build_activity(
    app: object,
    *,
    tenant_id: str,
    role: Role | None,
    area: Area | None,
    limit: int,
) -> ActivityResponse:
    """Project the bounded, windowed activity timeline; never raises."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=_window_days(app))
    try:
        with _activity_engine(app).begin() as connection:
            _set_statement_timeout(connection, _statement_timeout_ms(app))
            rows = (
                connection.execute(
                    text(_ACTIVITY_SQL),
                    {
                        "tenant": tenant_id,
                        "cutoff": cutoff,
                        "role": None if role is None else role.value,
                        "area": area,
                        "limit": limit,
                    },
                )
                .mappings()
                .all()
            )
            latest = cast(
                "datetime | None",
                connection.execute(text(_LATEST_SQL), {"tenant": tenant_id}).scalar_one_or_none(),
            )
    except Exception as exc:  # noqa: BLE001 - fail-open: never 500 an ops endpoint
        return ActivityResponse(
            source=SourceStatus(state=SourceState.UNAVAILABLE, detail=_failure_detail(exc)),
            role=role,
            area=area,
            limit=limit,
            entries=[],
        )
    entries = [_entry_from_row(row) for row in rows]
    state, detail = _source_verdict(latest, now, _window_days(app))
    return ActivityResponse(
        source=SourceStatus(state=state, last_data_at=latest, detail=detail),
        role=role,
        area=area,
        limit=limit,
        entries=entries,
    )


def build_roles(app: object, *, tenant_id: str) -> RolesResponse:
    """List every active membership's role with real counts; never raises."""
    checked_at = datetime.now(UTC)
    try:
        with _activity_engine(app).begin() as connection:
            _set_statement_timeout(connection, _statement_timeout_ms(app))
            member_rows = (
                connection.execute(text(_MEMBERS_SQL), {"tenant": tenant_id}).mappings().all()
            )
            role_rows = (
                connection.execute(
                    text(_ROLES_SQL),
                    {"tenant": tenant_id, "cutoff": checked_at - timedelta(days=_window_days(app))},
                )
                .mappings()
                .all()
            )
    except Exception as exc:  # noqa: BLE001 - fail-open: never 500 an ops endpoint
        logger.debug("activity: roles projection failed (%s)", type(exc).__name__)
        return RolesResponse(checked_at=checked_at, roles=[])
    members_by_role: dict[str, list[str]] = {}
    for row in member_rows:
        role_value = cast(str, row["role"])
        members_by_role.setdefault(role_value, []).append(cast(str, row["email"]))
    activity_by_role = {cast(str, row["role"]): row for row in role_rows}
    summaries: list[RoleSummary] = []
    for known in _ROLE_ORDER:
        emails = members_by_role.get(known.value)
        if emails is None:
            continue
        activity = activity_by_role.get(known.value)
        summaries.append(
            RoleSummary(
                role=known,
                active_members=len(emails),
                members=emails,
                recent_actions=0 if activity is None else int(activity["recent_actions"]),
                areas=[] if activity is None else _areas_from(activity["areas"]),
                last_active_at=(
                    None
                    if activity is None
                    else cast("datetime | None", activity["last_active_at"])
                ),
            )
        )
    return RolesResponse(checked_at=checked_at, roles=summaries)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry_from_row(row: object) -> ActivityEntry:
    """Rebuild one claim-blind entry from its projected row."""
    mapping = cast("dict[str, object]", row)
    raw_role = mapping["role"]
    raw_area = cast(str, mapping["area"])
    return ActivityEntry(
        at=cast(datetime, mapping["at"]),
        role=None if raw_role is None else Role(cast(str, raw_role)),
        actor=cast(str, mapping["actor"]),
        area=cast(Area, raw_area),
        action=cast(Action, mapping["action"]),
        outcome=cast(str, mapping["outcome"]),
        reference=cast(str, mapping["reference"]),
    )


def _areas_from(value: object) -> list[Area]:
    """Keep only the known areas from an ``array_agg`` result, sorted for stability."""
    raw = cast("list[str]", value) if isinstance(value, list) else []
    return cast("list[Area]", sorted(area for area in raw if area in _VALID_AREAS))


def _source_verdict(
    latest: datetime | None, now: datetime, window_days: float
) -> tuple[SourceState, str | None]:
    """Healthy / stale / unknown from the newest activity, honestly.

    A reachable database with no rows is ``unknown`` (there is no freshness to
    assert); rows older than the window are ``stale``; rows inside it are
    ``healthy``. No time is ever invented.
    """
    if latest is None:
        return SourceState.UNKNOWN, "reachable; no activity recorded"
    if latest < now - timedelta(days=window_days):
        return SourceState.STALE, f"reachable; last activity older than {window_days:g} days"
    return SourceState.HEALTHY, None


def _activity_engine(app: object) -> Engine:
    """The app's injection seam, else the review store's engine, else a fresh one."""
    injected = getattr(getattr(app, "state", None), _ENGINE_ATTR, None)
    if injected is not None:
        return cast(Engine, injected)
    store = getattr(getattr(app, "state", None), "store", None)
    engine = getattr(store, "engine", None)
    if engine is not None:
        return cast(Engine, engine)
    # Imported lazily: ``claimguard.review`` eagerly loads its app, which mounts
    # this router, so a top-level import would be circular.
    from claimguard.review.store import build_engine

    engine = build_engine()
    state = getattr(app, "state", None)
    if state is not None:
        setattr(state, _ENGINE_ATTR, engine)
    return engine


def _set_statement_timeout(connection: Connection, milliseconds: int) -> None:
    """Bound this transaction's statements; a slow query degrades, it does not hang."""
    connection.execute(
        text("SELECT set_config('statement_timeout', :ms, true)"), {"ms": str(milliseconds)}
    )


def _window_days(app: object) -> float:
    """The activity window: an injected override, else config, else the constant."""
    override = _positive_float(getattr(getattr(app, "state", None), _WINDOW_DAYS_ATTR, None))
    if override is not None:
        return override
    try:
        configured = get_settings().ops_activity_window_days
    except Exception:  # noqa: BLE001 - a broken config must not 500 an ops endpoint
        return float(ACTIVITY_WINDOW_DAYS)
    return configured if configured > 0 else float(ACTIVITY_WINDOW_DAYS)


def _statement_timeout_ms(app: object) -> int:
    """The per-statement timeout: an injected override, else config, else the constant."""
    override = getattr(getattr(app, "state", None), _STATEMENT_TIMEOUT_ATTR, None)
    if isinstance(override, int) and not isinstance(override, bool) and override > 0:
        return override
    try:
        configured = get_settings().ops_activity_statement_timeout_ms
    except Exception:  # noqa: BLE001 - a broken config must not 500 an ops endpoint
        return ACTIVITY_STATEMENT_TIMEOUT_MS
    return configured if configured > 0 else ACTIVITY_STATEMENT_TIMEOUT_MS


def _positive_float(value: object) -> float | None:
    """Return ``value`` as a positive finite float, or None when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    resolved = float(value)
    return resolved if resolved > 0 else None


def _failure_detail(exc: Exception) -> str:
    """Collapse a failure to one short, log-free line for the console."""
    collapsed = " ".join(f"activity source unavailable ({type(exc).__name__})".split())
    return collapsed


__all__ = [
    "ACTIVITY_STATEMENT_TIMEOUT_MS",
    "ACTIVITY_WINDOW_DAYS",
    "DEFAULT_ACTIVITY_LIMIT",
    "MAX_ACTIVITY_LIMIT",
    "ActivityEntry",
    "ActivityResponse",
    "RoleSummary",
    "RolesResponse",
    "build_activity",
    "build_roles",
    "router",
]
