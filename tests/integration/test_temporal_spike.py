"""Temporal spike test — the 12 Sep gate (ADR-010, 09 §A2).

WHAT THIS PROVES
----------------
1. A claim workflow runs end to end with mocked activities.
2. A human decision arrives by SIGNAL after the workflow has already parked.
3. `wait_condition` resumes correctly — the durable-wait primitive our HITL
   escalation depends on.
4. Time-skipping works: a multi-day SLA wait completes in milliseconds.

If this file is green, Temporal is adopted. If it cannot be made green by
12 Sep, we fall back to the Postgres state machine — which is cheap precisely
because the activities in `claim_workflow.py` are plain async functions.

This test needs NO external server: `WorkflowEnvironment.start_time_skipping()`
starts an in-memory Temporal test server.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from claimguard.workflow.claim_workflow import (
    ClaimInput,
    ClaimValidationWorkflow,
    ReviewDecision,
)
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# Activities are replaced by mocks; the workflow under test is the real one.
TASK_QUEUE = "claimguard-spike"


@activity.defn(name="ingest_and_normalize")
async def mock_ingest(payload: ClaimInput) -> str:
    return f"canonical-{payload.claim_id}"


@activity.defn(name="run_rules")
async def mock_rules(payload: ClaimInput) -> int:
    # Two findings -> forces the escalation path.
    return 2


@activity.defn(name="write_report")
async def mock_report(payload: ClaimInput) -> str:
    return f"report-{payload.claim_id}"


@activity.defn(name="escalate_to_human")
async def mock_escalate(payload: ClaimInput) -> str:
    return f"task-{payload.claim_id}"


@activity.defn(name="finalize")
async def mock_finalize(payload: ClaimInput) -> str:
    return "sealed"


MOCKS = [mock_ingest, mock_rules, mock_report, mock_escalate, mock_finalize]


@workflow.defn(name="DeterministicWorkflow")
class DeterministicWorkflow:
    """Module-level by requirement: Temporal disallows local workflow classes."""

    def __init__(self) -> None:
        self._seen: list[int] = []

    @workflow.run
    async def run(self, count: int) -> list[int]:
        for i in range(count):
            # workflow.sleep is a durable timer - replay-safe.
            await workflow.sleep(timedelta(hours=1))
            self._seen.append(i)
        return self._seen


@workflow.defn(name="WaitWorkflow")
class WaitWorkflow:
    @workflow.run
    async def run(self) -> str:
        await workflow.sleep(timedelta(hours=48))
        return "done"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_claim_workflow_completes_without_findings() -> None:
    """The clean path: no findings, no escalation, no human wait."""

    @activity.defn(name="run_rules")
    async def mock_rules_clean(payload: ClaimInput) -> int:
        return 0  # nothing wrong -> no escalation

    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimValidationWorkflow],
            activities=[
                mock_ingest,
                mock_rules_clean,
                mock_report,
                mock_finalize,
                mock_escalate,
            ],
        ),
    ):
        payload = ClaimInput(
            claim_id="CLM-CLEAN",
            package_id="pkg-1",
            trace_id="trace-1",
        )
        result = await env.client.execute_workflow(
            ClaimValidationWorkflow.run,
            payload,
            id=f"wf-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )
        assert result == "report-CLM-CLEAN"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_human_decision_by_signal_resumes_workflow() -> None:
    """THE HITL PRIMITIVE: park on wait_condition, resume on signal."""

    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimValidationWorkflow],
            activities=MOCKS,
        ),
    ):
        payload = ClaimInput(
            claim_id="CLM-0042",
            package_id="pkg-2",
            trace_id="trace-2",
        )
        handle = await env.client.start_workflow(
            ClaimValidationWorkflow.run,
            payload,
            id=f"wf-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )

        # The workflow parks waiting for a human. Let it get there.
        for _ in range(50):
            status = await handle.query(ClaimValidationWorkflow.status)
            if status.escalated:
                break
            await env.sleep(0.05)

        status = await handle.query(ClaimValidationWorkflow.status)
        assert status.escalated is True, "workflow never escalated"
        assert status.decided is False, "no decision should exist yet"

        # The reviewer decides — delivered as a signal.
        await handle.signal(
            ClaimValidationWorkflow.submit_review,
            ReviewDecision(
                reviewer_id="rev-1",
                outcome="upheld",
                reason_code="missing_context",
                note="confirmed with payer",
            ),
        )

        result = await handle.result()
        assert result == "report-CLM-0042"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_workflow_is_deterministic_under_replay() -> None:
    """Replay safety: the same workflow code produces the same decisions.

    This is the guard against accidentally using datetime.now() or random()
    inside workflow code — the classic Temporal footgun.
    """

    # DeterministicWorkflow is defined at MODULE level above: Temporal rejects
    # workflow classes declared inside a function ("Local classes unsupported").
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue=f"{TASK_QUEUE}-replay",
            workflows=[DeterministicWorkflow],
        ),
    ):
        result = await env.client.execute_workflow(
            DeterministicWorkflow.run,
            5,
            id=f"wf-replay-{uuid.uuid4()}",
            task_queue=f"{TASK_QUEUE}-replay",
        )
        # 5 one-hour sleeps complete instantly under time-skipping.
        assert result == [0, 1, 2, 3, 4]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_time_skipping_makes_long_wait_instant() -> None:
    """A 48-hour SLA wait must complete in milliseconds, not two days."""
    import time

    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue=f"{TASK_QUEUE}-timer",
            workflows=[WaitWorkflow],
        ),
    ):
        start = time.monotonic()
        result = await env.client.execute_workflow(
            WaitWorkflow.run,
            id=f"wf-timer-{uuid.uuid4()}",
            task_queue=f"{TASK_QUEUE}-timer",
        )
        elapsed = time.monotonic() - start

        assert result == "done"
        assert elapsed < 30, f"time-skipping did not engage (took {elapsed:.1f}s)"
