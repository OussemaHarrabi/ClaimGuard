"""Thin Temporal workflow for claim validation (ADR-010, 09 §A2).

WHY TEMPORAL
------------
HITL escalation means a claim can wait hours or days for a human. In Temporal
that wait costs nothing: `wait_condition` and `sleep` are durable timers, so a
parked claim holds zero threads, connections, and memory. It also gives us
time-skipping tests (a 48-hour SLA test runs in milliseconds) and a Replayer
that fails CI on non-determinism.

THE THIN-WORKFLOW RULE
----------------------
Workflows contain ORCHESTRATION ONLY — roughly 100 lines, no business logic.
Every real action is an activity: a plain async function taking and returning
serializable data. This is what makes the Postgres fallback cheap: if Temporal
becomes a liability, we rewrite this file's orchestration and touch nothing else.

DETERMINISM RULES (enforced by the sandbox and the CI Replayer)
---------------------------------------------------------------
Inside workflow code you MUST NOT use:
    datetime.now() / time.time()   -> use workflow.now()
    random / uuid4                 -> use workflow.random() / workflow.uuid4()
    threads, network I/O, global mutable state

Anything non-deterministic belongs in an activity.

FALLBACK (pre-designed, 1-2 days)
---------------------------------
The claims table already holds status; the reviewer API already exists. Without
Temporal a worker polls `WHERE status='awaiting_review'` and SLA timeouts are
computed lazily. Because activities are plain functions, the swap rewrites only
the orchestration layer.

GATE: 12 Sep. If the spike is not green by then, we cut to the Postgres state
machine. That is a planned outcome, not a failure.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

# ---------------------------------------------------------------------------
# Payloads — serializable dataclasses, never Temporal types.
#
# Event history is capped at 51,200 events / 50 MB, so bundles and narratives
# go to Postgres via activities, never through workflow arguments.
# ---------------------------------------------------------------------------


@dataclass
class ClaimInput:
    claim_id: str
    package_id: str
    trace_id: str


@dataclass
class ReviewDecision:
    """The human's decision, delivered by signal."""

    reviewer_id: str
    outcome: str
    reason_code: str
    note: str | None = None


@dataclass
class WorkflowStatus:
    """Typed query result. A bare dict[str, object] cannot be deserialized."""

    claim_id: str | None
    escalated: bool
    decided: bool


# ---------------------------------------------------------------------------
# Activities — fat, pure, explicitly retried
# ---------------------------------------------------------------------------


@activity.defn
async def ingest_and_normalize(payload: ClaimInput) -> str:
    """Ingest -> normalize -> persist canonical claim. Returns canonical id."""
    raise NotImplementedError("Bound in the worker; see ING-02/ING-04")


@activity.defn
async def run_rules(payload: ClaimInput) -> int:
    """Evaluate the rule catalogue. Returns the number of findings."""
    raise NotImplementedError("Bound in the worker; see RUL-06")


@activity.defn
async def write_report(payload: ClaimInput) -> str:
    """Assemble and persist the ValidationReport. Returns the report id."""
    raise NotImplementedError("Bound in the worker; see LLM-03/RUL-04")


@activity.defn
async def escalate_to_human(payload: ClaimInput) -> str:
    """Create a review task and notify the queue tier. Returns the task id."""
    raise NotImplementedError("Bound in the worker; see HIT-01/HIT-02")


@activity.defn
async def finalize(payload: ClaimInput) -> str:
    """Seal the report and mark the package handed off."""
    raise NotImplementedError("Bound in the worker; see AUD-02")


# ---------------------------------------------------------------------------
# Workflow — thin
# ---------------------------------------------------------------------------


@workflow.defn(name="ClaimValidationWorkflow")
class ClaimValidationWorkflow:
    """Orchestrates: normalize -> validate -> (human?) -> seal.

    Deliberately linear. No child workflows, no dynamic routing, no patching.
    """

    def __init__(self) -> None:
        self._decision: ReviewDecision | None = None
        self._escalated: bool = False
        self._claim_id: str | None = None

    @workflow.run
    async def run(self, payload: ClaimInput) -> str:
        # Explicit retry policy: the DEFAULT retries forever, which would turn a
        # deterministic bug in an activity into an infinite retry loop.
        retry = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1))
        timeout = timedelta(seconds=30)

        self._claim_id = payload.claim_id

        await workflow.execute_activity(
            ingest_and_normalize,
            payload,
            retry_policy=retry,
            start_to_close_timeout=timeout,
        )

        findings_count = await workflow.execute_activity(
            run_rules,
            payload,
            retry_policy=retry,
            start_to_close_timeout=timeout,
        )

        report_id = await workflow.execute_activity(
            write_report,
            payload,
            retry_policy=retry,
            start_to_close_timeout=timeout,
        )

        # Mandatory-topic escalation is NEVER confidence-gated. When findings
        # exist we wait for a human — however long that takes.
        if findings_count > 0:
            self._escalated = True
            await workflow.execute_activity(
                escalate_to_human,
                payload,
                retry_policy=retry,
                start_to_close_timeout=timeout,
            )

            # Durable wait: survives worker and server restarts, costs nothing.
            await workflow.wait_condition(lambda: self._decision is not None)

        await workflow.execute_activity(
            finalize,
            payload,
            retry_policy=retry,
            start_to_close_timeout=timeout,
        )
        return report_id

    @workflow.signal
    async def submit_review(self, decision: ReviewDecision) -> None:
        """The human's decision arrives here, from the API layer."""
        self._decision = decision

    @workflow.query
    def status(self) -> WorkflowStatus:
        """Read-only view for the API/UI. Adds no history events."""
        return WorkflowStatus(
            claim_id=self._claim_id,
            escalated=self._escalated,
            decided=self._decision is not None,
        )


def new_workflow_id(claim_id: str) -> str:
    """Human-readable, unique workflow id."""
    return f"claim-{claim_id}-{uuid.uuid4().hex[:8]}"


__all__ = [
    "ClaimInput",
    "ClaimValidationWorkflow",
    "ReviewDecision",
    "WorkflowStatus",
    "escalate_to_human",
    "finalize",
    "ingest_and_normalize",
    "new_workflow_id",
    "run_rules",
    "write_report",
]
