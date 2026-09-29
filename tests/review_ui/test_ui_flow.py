"""The flows the page drives, end to end, through the API it calls.

These tests need PostgreSQL (skipped automatically when it is unreachable; see
``tests/review_ui/__init__.py``) and drive the real ASGI app in-process through
httpx: no browser, no server, but the real routes, the real store and the real
schema. Each test performs the sequence ``app.js`` performs — read the queue,
open a claim's 15 results, record a decision, submit a corrected envelope — so a
failure here is a failure of the interface, not of a hand-written request.

The API's own contract (statuses, state machine, 404/409 handling) is already
covered by ``tests/review/test_review_api.py``; these tests cover what the page
needs on top of it: that the page and the API are one app, that the API's refusal
is surfaced rather than hidden, and that a correction is a new version while the
original run stays readable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.edu import attachment, authorization, line
from tests.review.conftest import FAILING_RULE, Sandbox, requires_db
from tests.review_ui.conftest import HARNESS, requires_node, run_node

pytestmark = [pytest.mark.integration, requires_db]

#: A payload that would execute if the page ever wrote claim text as markup.
SCRIPT_PAYLOAD = "<script>alert('attachment-text')</script>"


async def submit(client: httpx.AsyncClient, envelope: dict[str, Any]) -> dict[str, Any]:
    """POST /v1/claims, as the page's queue would after a submission."""
    response = await client.post("/v1/claims", json={"claim": envelope})
    assert response.status_code == 201, response.text
    return response.json()


async def test_the_page_is_served_by_the_same_app_that_answers_the_api(
    client: httpx.AsyncClient,
) -> None:
    """One app, one port: the interface is not a second service to deploy."""
    page = await client.get("/review")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "PASS means this specific check passed on the supplied data" in page.text
    assert (await client.get("/v1/health")).status_code == 200


async def test_the_queue_the_page_reads_filters_and_counts_unresolved_checks(
    client: httpx.AsyncClient, sandbox: Sandbox
) -> None:
    """Behaviour 4: filters, original values and unresolved-check counts."""
    envelope = sandbox.coverage_lapse()
    run_id = (await submit(client, envelope))["run"]["run_id"]

    queue = (
        await client.get(
            "/v1/queue",
            params={"status": "FAIL", "severity": "high", "rule_id": FAILING_RULE},
        )
    ).json()
    assert queue["filters"] == {
        "status": "FAIL",
        "severity": "high",
        "rule_id": FAILING_RULE,
        "claim_id": None,
        "include_all": False,
    }
    assert queue["counts"]["findings"] >= 1
    assert queue["counts"]["unresolved"] >= 1
    assert queue["counts"]["by_rule_status"]["FAIL"] == queue["counts"]["findings"]
    assert all(item["record"]["rule_id"] == FAILING_RULE for item in queue["items"])
    assert all(item["record"]["status"] == "FAIL" for item in queue["items"])
    assert all(item["needs_attention"] for item in queue["items"])

    mine = next(claim for claim in queue["claims"] if claim["claim_id"] == envelope["claim_id"])
    assert mine["run_id"] == run_id
    assert mine["version"] == 1
    assert mine["unresolved"] == 1

    # The evidence the page prints as `path = value` is the ORIGINAL value.
    failing = next(item for item in queue["items"] if item["claim_id"] == envelope["claim_id"])
    evidence = {entry["path"]: entry["value"] for entry in failing["record"]["evidence"]}
    assert evidence["/coverage/end_date"] == envelope["coverage"]["end_date"]


async def test_the_decision_round_trip_shows_the_apis_own_refusal(
    client: httpx.AsyncClient, sandbox: Sandbox
) -> None:
    """Behaviour 5, and the 422 is displayed, never papered over."""
    envelope = sandbox.coverage_lapse()
    run_id = (await submit(client, envelope))["run"]["run_id"]

    # What the page does when the reviewer field is empty: it still submits.
    refused = await client.post(
        f"/v1/runs/{run_id}/decisions",
        json={
            "rule_id": FAILING_RULE,
            "action": "confirm_issue",
            "actor": "",
            "reason": "looks wrong",
        },
    )
    assert refused.status_code == 422
    body = refused.json()
    assert body["detail"][0]["loc"] == ["body", "actor"]
    assert "must not be blank" in body["detail"][0]["msg"]

    # Same with the reason left blank.
    refused_reason = await client.post(
        f"/v1/runs/{run_id}/decisions",
        json={
            "rule_id": FAILING_RULE,
            "action": "confirm_issue",
            "actor": "rev-1",
            "reason": "  ",
        },
    )
    assert refused_reason.status_code == 422
    assert refused_reason.json()["detail"][0]["loc"] == ["body", "reason"]

    # Nothing was recorded by either refusal.
    assert (await client.get(f"/v1/runs/{run_id}/decisions")).json()["entries"] == []

    recorded = await client.post(
        f"/v1/runs/{run_id}/decisions",
        json={
            "rule_id": FAILING_RULE,
            "action": "dismiss_with_reason",
            "actor": "rev-1",
            "reason": "the source record proves the service date",
        },
    )
    assert recorded.status_code == 201
    payload = recorded.json()
    assert payload["review"]["status"] == "dismissed"
    assert payload["review"]["unresolved"] is False
    assert payload["decision"]["event"]["original_status"] == "FAIL"
    assert len(payload["audit"]["chain_hash"]) == 64

    history = (await client.get(f"/v1/runs/{run_id}/decisions")).json()
    assert [entry["decision"]["event"]["actor"] for entry in history["entries"]] == ["rev-1"]


async def test_a_correction_is_a_new_version_and_the_original_stays_readable(
    client: httpx.AsyncClient, sandbox: Sandbox
) -> None:
    """The recheck the page offers: a new run version, nothing overwritten."""
    envelope = sandbox.coverage_lapse()
    original = await submit(client, envelope)
    original_run = original["run"]["run_id"]
    assert original["by_status"]["FAIL"] == 1

    # A decision recorded on version 1 before the correction.
    decided = await client.post(
        f"/v1/runs/{original_run}/decisions",
        json={
            "rule_id": FAILING_RULE,
            "action": "confirm_issue",
            "actor": "rev-1",
            "reason": "the coverage period really does end early",
        },
    )
    assert decided.status_code == 201

    corrected = sandbox.corrected(envelope)
    recheck = await client.post(
        f"/v1/claims/{envelope['claim_id']}/recheck",
        json={"claim": corrected, "actor": "rev-1"},
    )
    assert recheck.status_code == 201, recheck.text
    new_run = recheck.json()["run"]
    assert new_run["version"] == 2
    assert new_run["claim_id"] == envelope["claim_id"]
    assert new_run["supersedes_run_id"] == original_run
    assert new_run["initiated_by"] == "rev-1"
    assert recheck.json()["by_status"]["FAIL"] == 0
    assert recheck.json()["run"]["run_id"] != original_run

    # The original run is untouched: same identity, same 15 records, same FAIL.
    still_there = await client.get(f"/v1/runs/{original_run}/results")
    assert still_there.status_code == 200
    assert still_there.json()["run"]["version"] == 1
    assert still_there.json()["run"]["supersedes_run_id"] is None
    records = still_there.json()["results"]
    assert len(records) == 15
    failing = next(record for record in records if record["rule_id"] == FAILING_RULE)
    assert failing["status"] == "FAIL"
    evidence = {entry["path"]: entry["value"] for entry in failing["evidence"]}
    assert evidence["/coverage/end_date"] == envelope["coverage"]["end_date"]

    # The decision recorded on version 1 is still readable, and the run refuses a
    # new one: the reviewer works the live version, and history is not rewritten.
    history = (await client.get(f"/v1/runs/{original_run}/decisions")).json()
    assert [entry["decision"]["event"]["action"] for entry in history["entries"]] == [
        "confirm_issue"
    ]
    late = await client.post(
        f"/v1/runs/{original_run}/decisions",
        json={
            "rule_id": FAILING_RULE,
            "action": "request_information",
            "actor": "rev-1",
            "reason": "too late: this version is superseded",
        },
    )
    assert late.status_code == 409
    assert "superseded" in json.dumps(late.json())

    # The default queue lists the checks that need attention. The corrected version
    # has none, so the claim leaves the queue — and with include_all the reviewer
    # still sees all 15 of its checks, at version 2. Passing checks are not
    # unresolved findings.
    attention = (await client.get("/v1/queue", params={"claim_id": envelope["claim_id"]})).json()
    assert attention["items"] == []
    assert attention["claims"] == []

    full = (
        await client.get(
            "/v1/queue", params={"claim_id": envelope["claim_id"], "include_all": "true"}
        )
    ).json()
    assert full["counts"]["findings"] == 15
    assert full["claims"][0]["version"] == 2
    assert full["claims"][0]["unresolved"] == 0
    assert all(item["version"] == 2 for item in full["items"])
    assert full["counts"]["by_rule_status"]["FAIL"] == 0


@requires_node
async def test_attachment_text_reaching_the_page_cannot_become_markup(
    client: httpx.AsyncClient, sandbox: Sandbox, tmp_path: Path
) -> None:
    """The real payload path: API → evidence → the shipped renderer → text."""
    envelope = sandbox.claim()
    envelope["lines"] = [
        line(
            service_code="SVC-IMAGE", unit_price=1500, net_amount=1500, authorization_id="AUTH-UI-1"
        )
    ]
    envelope["total_amount"] = 1500
    envelope["authorizations"] = [authorization(authorization_id="AUTH-UI-1")]
    envelope["attachments"] = [
        attachment(attachment_id="DOC-UI-1", document_status="draft", text=SCRIPT_PAYLOAD)
    ]
    run_id = (await submit(client, envelope))["run"]["run_id"]

    results = (await client.get(f"/v1/runs/{run_id}/results")).json()["results"]
    document_check = next(record for record in results if record["rule_id"] == "R010")
    assert document_check["status"] == "UNABLE_TO_ASSESS"
    attachments = next(
        entry for entry in document_check["evidence"] if entry["path"] == "/attachments"
    )
    # The API hands the interface the submitter's text, verbatim.
    assert attachments["value"][0]["text"] == SCRIPT_PAYLOAD

    source = tmp_path / "payload.json"
    source.write_text(
        json.dumps({"finding": {"record": document_check, "options": {}}}), encoding="utf-8"
    )
    rendered = json.loads(run_node(str(HARNESS), str(source)))
    assert "script" not in rendered["elements"]
    assert "<script" not in rendered["html"]
    assert "&lt;script&gt;alert('attachment-text')&lt;/script&gt;" in rendered["html"]
    assert SCRIPT_PAYLOAD in rendered["text"]
