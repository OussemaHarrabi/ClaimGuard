"""Integration tests for the review HTTP surface.

**These tests need PostgreSQL** (skipped automatically when it is unreachable; see
``tests/review/__init__.py``). They drive the real ASGI app in-process through
httpx — no server, no network, but the real routes, the real store and the real
schema.

The scenarios mirror the responsibilities the pack assigns to the review
interface: submit, read the 15 results, filter the queue with unresolved counts,
record a decision (with all four actions) and recheck a corrected claim as a new
version.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from claimguard.edu.envelope import RESULT_KEYS, RULE_VERSION
from claimguard.review.models import ReviewAction
from claimguard.review.store import ReviewStore

from tests.review.conftest import FAILING_RULE, Sandbox, requires_db

pytestmark = [pytest.mark.integration, requires_db]


async def submit(client: httpx.AsyncClient, envelope: dict[str, Any]) -> httpx.Response:
    return await client.post("/v1/claims", json={"claim": envelope})


async def decide(
    client: httpx.AsyncClient, run_id: str, action: str, **overrides: Any
) -> httpx.Response:
    payload: dict[str, Any] = {
        "rule_id": FAILING_RULE,
        "action": action,
        "actor": "rev-1",
        "reason": "checked against the source record",
    }
    payload.update(overrides)
    return await client.post(f"/v1/runs/{run_id}/decisions", json=payload)


async def test_health_reports_the_schema_and_the_rule_catalogue(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["schema_revision"] == "0002"
    assert body["database"] == "ready"
    assert body["rules_ready"] is True
    assert body["engine_rule_version"] == RULE_VERSION


async def test_submitting_a_claim_returns_its_fifteen_results(
    client: httpx.AsyncClient, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    response = await submit(client, envelope)
    assert response.status_code == 201
    body = response.json()
    assert body["results"] == 15
    assert body["needs_attention"] == 1
    assert body["by_status"]["FAIL"] == 1
    assert body["duplicate"] is False
    assert body["run"]["version"] == 1
    assert body["audit"]["kind"] == "validated"
    assert len(body["audit"]["chain_hash"]) == 64

    run_id = body["run"]["run_id"]
    results = (await client.get(f"/v1/runs/{run_id}/results")).json()["results"]
    assert len(results) == 15
    assert [record["rule_id"] for record in results] == [f"R{index:03d}" for index in range(1, 16)]
    assert all(set(record) == set(RESULT_KEYS) for record in results)
    r003 = next(record for record in results if record["rule_id"] == FAILING_RULE)
    assert r003["status"] == "FAIL"
    assert r003["evidence"], "a FAIL must cite evidence"
    assert r003["requires_human_review"] is True

    metadata = await client.get(f"/v1/runs/{run_id}")
    assert metadata.status_code == 200
    assert metadata.json()["run"] == body["run"]


async def test_a_malformed_envelope_is_rejected_with_the_engines_message(
    client: httpx.AsyncClient, sandbox: Sandbox
) -> None:
    incomplete = sandbox.coverage_lapse()
    del incomplete["coverage"]["start_date"]
    response = await submit(client, incomplete)
    assert response.status_code == 422
    assert "Coverage keys must match the transport contract" in response.json()["detail"]

    extra = sandbox.coverage_lapse()
    extra["unexpected_key"] = "ignored?"
    assert (await submit(client, extra)).status_code == 422

    missing = sandbox.coverage_lapse()
    del missing["currency"]
    assert (await submit(client, missing)).status_code == 422


async def test_unknown_runs_are_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/runs/RUN-nope")).status_code == 404
    assert (await client.get("/v1/runs/RUN-nope/results")).status_code == 404
    assert (await client.get("/v1/runs/RUN-nope/decisions")).status_code == 404
    assert (await decide(client, "RUN-nope", ReviewAction.CONFIRM_ISSUE.value)).status_code == 404


async def test_a_decision_without_an_actor_or_reason_is_rejected(
    client: httpx.AsyncClient, sandbox: Sandbox
) -> None:
    run_id = (await submit(client, sandbox.coverage_lapse())).json()["run"]["run_id"]

    without_reason = await client.post(
        f"/v1/runs/{run_id}/decisions",
        json={"rule_id": FAILING_RULE, "action": "confirm_issue", "actor": "rev-1"},
    )
    assert without_reason.status_code == 422
    assert without_reason.json()["detail"][0]["loc"] == ["body", "reason"]

    without_actor = await client.post(
        f"/v1/runs/{run_id}/decisions",
        json={"rule_id": FAILING_RULE, "action": "confirm_issue", "reason": "no actor"},
    )
    assert without_actor.status_code == 422
    assert without_actor.json()["detail"][0]["loc"] == ["body", "actor"]

    blank = await decide(client, run_id, ReviewAction.CONFIRM_ISSUE.value, reason="   ")
    assert blank.status_code == 422

    unknown_action = await decide(client, run_id, "approve_claim")
    assert unknown_action.status_code == 422

    unknown_rule = await decide(client, run_id, ReviewAction.CONFIRM_ISSUE.value, rule_id="R999")
    assert unknown_rule.status_code == 422

    assert (await client.get(f"/v1/runs/{run_id}/decisions")).json()["entries"] == []


async def test_the_four_actions_are_accepted_and_reported(
    client: httpx.AsyncClient, sandbox: Sandbox
) -> None:
    run_id = (await submit(client, sandbox.coverage_lapse())).json()["run"]["run_id"]

    asked = await decide(
        client, run_id, ReviewAction.REQUEST_INFORMATION.value, reason="need the note"
    )
    assert asked.status_code == 201
    assert asked.json()["decision"]["event"]["action"] == "request_information"
    assert asked.json()["decision"]["event"]["original_status"] == "FAIL"
    assert asked.json()["review"]["status"] == "info_requested"
    assert asked.json()["review"]["unresolved"] is True

    confirmed = await decide(
        client, run_id, ReviewAction.CONFIRM_ISSUE.value, reason="answer received"
    )
    assert confirmed.status_code == 201
    assert confirmed.json()["review"]["status"] == "confirmed"
    assert confirmed.json()["review"]["unresolved"] is False
    assert confirmed.json()["review"]["decision_count"] == 2

    # The pack's state machine refuses a repeat of the same terminal answer.
    repeated = await decide(client, run_id, ReviewAction.CONFIRM_ISSUE.value)
    assert repeated.status_code == 409
    assert repeated.json()["error"] == "IllegalReviewTransitionError"

    reopened = await decide(
        client, run_id, ReviewAction.REQUEST_INFORMATION.value, reason="more data"
    )
    assert reopened.status_code == 201
    dismissed = await decide(
        client, run_id, ReviewAction.DISMISS_WITH_REASON.value, reason="data proves it"
    )
    assert dismissed.status_code == 201
    assert dismissed.json()["review"]["status"] == "dismissed"

    history = (await client.get(f"/v1/runs/{run_id}/decisions")).json()
    assert [entry["review"]["status"] for entry in history["entries"]] == [
        "info_requested",
        "confirmed",
        "info_requested",
        "dismissed",
    ]
    assert all(len(entry["decision"]["event"]) == 7 for entry in history["entries"])


async def test_the_queue_filters_and_counts_unresolved_checks(
    client: httpx.AsyncClient, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    run_id = (await submit(client, envelope)).json()["run"]["run_id"]

    queue = (await client.get("/v1/queue", params={"claim_id": envelope["claim_id"]})).json()
    assert queue["counts"]["findings"] == 1
    assert queue["counts"]["unresolved"] == 1
    assert queue["counts"]["by_review_status"] == {"unreviewed": 1}
    assert queue["claims"][0]["claim_id"] == envelope["claim_id"]
    assert queue["claims"][0]["unresolved"] == 1
    item = queue["items"][0]
    assert item["record"]["rule_id"] == FAILING_RULE
    assert item["review"]["status"] == "unreviewed"
    assert item["needs_attention"] is True
    assert item["record"]["evidence"], "the queue shows original values, not just a verdict"

    by_rule = (
        await client.get(
            "/v1/queue", params={"claim_id": envelope["claim_id"], "rule_id": FAILING_RULE}
        )
    ).json()
    assert len(by_rule["items"]) == 1
    by_other_rule = (
        await client.get("/v1/queue", params={"claim_id": envelope["claim_id"], "rule_id": "R004"})
    ).json()
    assert by_other_rule["items"] == []
    assert by_other_rule["counts"]["findings"] == 0

    high = (
        await client.get("/v1/queue", params={"claim_id": envelope["claim_id"], "severity": "high"})
    ).json()
    assert len(high["items"]) == 1
    low = (
        await client.get("/v1/queue", params={"claim_id": envelope["claim_id"], "severity": "low"})
    ).json()
    assert low["items"] == []

    passing = (
        await client.get(
            "/v1/queue",
            params={"claim_id": envelope["claim_id"], "status": "PASS", "include_all": True},
        )
    ).json()
    assert len(passing["items"]) == 11

    assert (await client.get("/v1/queue", params={"status": "nonsense"})).status_code == 422

    await decide(client, run_id, ReviewAction.CONFIRM_ISSUE.value)
    resolved = (await client.get("/v1/queue", params={"claim_id": envelope["claim_id"]})).json()
    assert resolved["counts"]["unresolved"] == 0
    assert resolved["counts"]["resolved"] == 1
    assert resolved["items"][0]["review"]["status"] == "confirmed"


async def test_a_correction_creates_a_new_version_and_keeps_the_original(
    client: httpx.AsyncClient, store: ReviewStore, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    first = (await submit(client, envelope)).json()
    run_id = first["run"]["run_id"]
    await decide(
        client, run_id, ReviewAction.MARK_CORRECTED_FOR_RECHECK.value, reason="coverage dates"
    )

    corrected = sandbox.corrected(envelope)
    recheck = await client.post(
        f"/v1/claims/{envelope['claim_id']}/recheck", json={"claim": corrected, "actor": "rev-1"}
    )
    assert recheck.status_code == 201
    new = recheck.json()
    assert new["run"]["version"] == 2
    assert new["run"]["supersedes_run_id"] == run_id
    assert new["run"]["initiated_by"] == "rev-1"
    assert new["audit"]["kind"] == "validated"

    new_results = (await client.get(f"/v1/runs/{new['run']['run_id']}/results")).json()["results"]
    corrected_r003 = next(record for record in new_results if record["rule_id"] == FAILING_RULE)
    assert corrected_r003["status"] == "PASS"
    assert new["by_status"].get("FAIL", 0) == 0

    original = (await client.get(f"/v1/runs/{run_id}/results")).json()["results"]
    assert original == [record.model_dump(mode="json") for record in store.get_results(run_id)]
    original_r003 = next(record for record in original if record["rule_id"] == FAILING_RULE)
    assert original_r003["status"] == "FAIL", "the original run's records changed"
    assert (await client.get(f"/v1/runs/{run_id}/decisions")).json()["entries"], (
        "the original run's decisions disappeared"
    )

    identical = await client.post(
        f"/v1/claims/{envelope['claim_id']}/recheck", json={"claim": corrected, "actor": "rev-1"}
    )
    assert identical.status_code == 409
    assert "identical" in identical.json()["detail"]

    late = await decide(client, run_id, ReviewAction.CONFIRM_ISSUE.value, rule_id="R004")
    assert late.status_code == 409
    assert "superseded" in late.json()["detail"]

    queue = (
        await client.get(
            "/v1/queue", params={"claim_id": envelope["claim_id"], "include_all": True}
        )
    ).json()
    assert queue["claims"][0]["version"] == 2
    assert {item["run_id"] for item in queue["items"]} == {new["run"]["run_id"]}


async def test_a_recheck_needs_a_claim_that_was_submitted(
    client: httpx.AsyncClient, sandbox: Sandbox
) -> None:
    envelope = sandbox.coverage_lapse()
    assert (
        await client.post(
            f"/v1/claims/{envelope['claim_id']}/recheck", json={"claim": envelope, "actor": "rev-1"}
        )
    ).status_code == 404

    await submit(client, envelope)
    other = sandbox.corrected(envelope)
    other["claim_id"] = "CG-SOMEONE-ELSE"
    sandbox.register(other)
    mismatched = await client.post(
        f"/v1/claims/{envelope['claim_id']}/recheck", json={"claim": other, "actor": "rev-1"}
    )
    assert mismatched.status_code == 409
    assert "not" in mismatched.json()["detail"]

    no_actor = await client.post(
        f"/v1/claims/{envelope['claim_id']}/recheck", json={"claim": sandbox.corrected(envelope)}
    )
    assert no_actor.status_code == 422
